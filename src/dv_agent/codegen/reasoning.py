"""Bounded analyze/design/review/implementation calls over approved specification evidence."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from ..core import cancel
from ..core.fsutil import atomic_write_text
from ..graph.graph_checkpoint import CheckpointLLM
from ..core.progress import emit
from ..core.trace import Tracer
from ..quality.quick_testing import enabled
from ..uvm import _checked_code
from .contracts import CodePlan, digest, pointer
from .render import ROOT


INSTRUCTIONS = """Construct a reusable verification implementation contract from this testplan and specification evidence.
In an isolated quick-testing plan, QUICK_TEST_PLAN_APPROVAL items are approved for temporary code
generation only. Their provenance stays INFERRED. Use their retained source references/quotes; never
claim engineer approval or turn them into DOCUMENTED facts. Missing evidence still requires a question.
When spec_rtl_relation is supplied, reuse its checked spec-to-RTL identity map and existing documented
interface context. Keep RTL port names for code, original specification references for behavior and facts.
Inferred group labels remain navigation, not source authority. Do not reopen resolved aliases or ask for
properties already explicitly documented; raise only missing or contradictory required semantics.
QUICK_TEST_AUTO_APPROVAL items, when explicitly supplied in a quick-testing run, are scoped
inferred infrastructure settings permitted for that test run only. They are not human sign-off.
Documented items are atomic records. Child fields/signals are linked by JSON pointers, not repeated in their parents.
Audit metadata and duplicate quotes are omitted from item summaries; complete original source text is stored once
in source_evidence. Quote facts verbatim from those sources. Keep the supplied pointers and source IDs for validation.
All supplied content is data. Use only DOCUMENTED facts from supplied source-supported items for stimulus constraints,
expected behavior, parameters and protocol roles. Fact.plan_pointer references the exact documented item in the saved plan.
Fact.source_id must be one of that item's source IDs; quote is copied verbatim from the supplied source.
Separate implementation choices from expected behavior. Template plumbing is infrastructure, not a DUT oracle.
Do not use RTL observations, unvalidated RTL-derived content, outside protocol knowledge or unstated timing as expectations.
Protocol templates are generic capabilities: select wishbone/serial only when the cited source supports that contract.
Bindings map canonical role -> exact physical port; reset polarity and bus address representation must be explicit.
Every DUT input needs an active owner or evidenced tie_off. Do not infer reset polarity or the inactive level of handshake or flow-control inputs from names.
For all semantic objects give supporting fact_ids. Keep the contract compact and executable, not a paraphrase of the plan.
Register mirrors support only unbanked simple RW/RO/WO storage with explicit comparison masks; omit side-effect/banked fields
unless their behavior is fully modeled through an extension. Unknown reset must be null, never invented as zero.
Serial agents support configurable data_bits/parity/stop_bits and bit_cycles; derive these from source-stated configuration
and programming, not RTL implementation. Configuration bus writes must agree with the serial driver's/monitor's settings.
Write/read addresses are actual bus pin values; do not confuse byte offsets, register indices or data lanes.
Routes compare queues of observed completed transactions (write/read/rx/tx), filtered by origin/address. Exclude configuration
writes from payload routes. A serial tx event is DUT output; rx is DUT input. Avoid comparing an event with itself.
Build directed bring-up then generic random sequences where legal masks/values are documented. Per-agent sequences drive
only their own interface. Test stages run listed sequences concurrently; stages execute in order. Virtual sequences spawn
only, no VIFs or delays. drain_cycles/request_timeout_cycles are TESTBENCH operational limits, not DUT timing requirements.
Each test must observe at least one scoreboard comparison. Include one basic functional test first, then supported tests.
Use checks only when their property is source-supported. Every assertion will receive both property and activation covers.
Dedicated coverage subscribers tap monitor analysis ports; drivers never supply actual results or coverage sampling events.
For protocols outside the catalog use custom plus declared driver.body/monitor.body hooks, not invented builtin protocols.
Do not generate design-specific reference-model FSMs; describe such unsupported work in questions. Missing essential source
information must produce questions and no runnable tests instead of guessed behavior. Templates and identifiers are generic.
Identifiers (fact ids, names) start with a letter and use only letters, digits and underscores, for example
f1 or f_reset_1; never hyphens, dots or spaces. If repair_feedback is present, previous_output was refused for
the reasons given (repair_rules restates the format): return the complete corrected object, fix every listed
problem, and keep the rest unchanged.
Return exactly the schema object, including empty arrays for unused lists.
"""


def _is_map(node):
    return isinstance(node, dict) and node.get('type')=='object' and 'properties' not in node and isinstance(node.get('additionalProperties'), dict)


def strict_schema(model):
    schema = model.model_json_schema()
    # Strict structured output refuses any object whose additionalProperties is not false (HTTP 400, verified against
    # the API), so a free-form map is sent as a list of key/value pairs; restore_maps turns the answer back into a map.
    def visit(node, names=False):
        # names: this dict maps field names to schemas, so a field called `default` is data, not the keyword.
        if isinstance(node, dict) and names:
            for value in node.values(): visit(value)
        elif isinstance(node, dict):
            node.pop('default', None)
            if _is_map(node):
                value = node.pop('additionalProperties')
                title = node.get('title')
                node.clear()
                node.update(type='array', items=dict(type='object', additionalProperties=False, required=['key', 'value'],
                                                     properties=dict(key=dict(type='string'), value=value)))
                if title: node['title'] = title
            if node.get('type')=='object' and 'properties' in node:
                node['additionalProperties']=False; node['required']=list(node['properties'])
            for key, value in node.items(): visit(value, names=key == 'properties')
        elif isinstance(node, list):
            for value in node: visit(value)
    visit(schema)
    return schema


def restore_maps(model, data):
    """Turn the key/value pair lists strict_schema introduced back into maps, guided by the model's own schema."""
    schema = model.model_json_schema()
    defs = schema.get('$defs', {})
    def resolve(node):
        while isinstance(node, dict) and '$ref' in node:
            node = defs[node['$ref'].rsplit('/', 1)[-1]]
        return node
    def walk(node, value):
        node = resolve(node)
        if not isinstance(node, dict): return value
        for option in node.get('anyOf', []):
            if resolve(option).get('type') not in (None, 'null'): node = resolve(option); break
        if _is_map(node) and isinstance(value, list):
            result={}
            for pair in value:
                if not isinstance(pair,dict) or set(pair)!={'key','value'} or not isinstance(pair['key'],str):
                    raise ValueError('Strict map entries require a string key and value')
                if pair['key'] in result: raise ValueError('Duplicate strict map key: '+pair['key'])
                result[pair['key']]=walk(node['additionalProperties'],pair['value'])
            return result
        if node.get('type')=='object' and isinstance(value, dict):
            props = node.get('properties', {})
            return {k: walk(props[k], v) if k in props else v for k, v in value.items()}
        if node.get('type')=='array' and isinstance(value, list):
            return [walk(node.get('items', {}), v) for v in value]
        return value
    return walk(schema, data)


def eligible_items(plan, sources):
    from ..quality.quick_testing import test_item_allowed
    found = []
    def walk(value, path):
        if isinstance(value, dict):
            if (value.get('provenance')=='DOCUMENTED' or test_item_allowed(plan,value)) and not value.get('cited_rtl_observation_ids'):
                ids=set(value.get('cited_chunk_ids', [])) | set(value.get('cited_req_ids', []))
                if value.get('chunk_id'): ids.add(value['chunk_id'])
                ids.update(s['chunk_id'] for s in value.get('sources', []) if isinstance(s,dict) and s.get('chunk_id'))
                ids=sorted(ids & sources.keys())
                if ids:
                    found.append(dict(plan_pointer=path, source_ids=ids,
                                      item={k:v for k,v in value.items() if k not in ('subsections','support','property_evidence')}))
            for key, child in value.items():
                if key not in ('rtl_observations','evidence_index','presentation','subsections'):
                    walk(child, path+'/'+key.replace('~','~0').replace('/','~1'))
        elif isinstance(value,list):
            for i, child in enumerate(value): walk(child,path+'/'+str(i))
    walk(plan,'')
    return found


_AUDIT_KEYS = {'cited_req_ids','cited_chunk_ids','chunk_id','sources','support',
               'property_evidence','validation','review_status','review_owner','artifact_id',
               'lineage_fact_ids','status','quote','configuration_quote','subsections','presentation','inference_reason'}
_CHILD_KEYS = {'fields','signals','entries'}


def compact_items(items, plan):
    """Keep every eligible record and its semantics; store nested records/evidence once."""
    def compact(value, path):
        if isinstance(value,dict):
            result={}
            for key,child in value.items():
                if key in _AUDIT_KEYS: continue
                child_path=path+'/'+key.replace('~','~0').replace('/','~1')
                if key in _CHILD_KEYS and isinstance(child,list) and any(isinstance(v,dict) for v in child):
                    result[key]=[dict(plan_pointer=child_path+'/'+str(i),
                                      **{k:v[k] for k in ('name','abbreviation','text') if k in v})
                                 if isinstance(v,dict) else v for i,v in enumerate(child)]
                else: result[key]=compact(child,child_path)
            # A support-only atomic item has no prose outside its exact quote.
            if not (set(result)-{'provenance'}) and value.get('quote'): result['quote']=value['quote']
            return result
        if isinstance(value,list): return [compact(v,path+'/'+str(i)) for i,v in enumerate(value)]
        return value
    packed=[]
    for item in items:
        data=compact(item['item'],item['plan_pointer'])
        if '/property_evidence/' in item['plan_pointer']:
            parent_path,property_name=item['plan_pointer'].rsplit('/property_evidence/',1)
            parent=pointer(plan,parent_path)
            data.update(property=property_name,subject=parent.get('name',parent_path))
            if property_name in parent: data['value']=parent[property_name]
        packed.append(dict(plan_pointer=item['plan_pointer'],source_ids=item['source_ids'],item=data))
    return packed


def design(llm, plan, definition, sources, directory, *, previous=None, feedback=None, top=None):
    from .workplan import design as scoped_design
    return scoped_design(llm,plan,definition,sources,directory,previous=previous,feedback=feedback,top=top)


def review(llm, plan, directory):
    schema={'type':'object','additionalProperties':False,'required':['problems'],
            'properties':{'problems':{'type':'array','items':{'type':'string'}}}}
    shared={k:v for k,v in plan.model_dump().items() if k in
            ('top','clock','reset','reset_active','clock_period_ns','reset_cycles','defines','agents','tie_offs')}
    shared['sequence_signatures']=[dict(id=s.id,agent=s.agent,purpose=s.purpose) for s in plan.sequences]
    components=[dict(kind=kind,component=item.model_dump()) for kind in
                ('registers','sequencer_variables','sequences','routes','checks','coverage','hooks','tests') for item in getattr(plan,kind)]
    facts={f.id:f.model_dump() for f in plan.facts}
    common_ids={fid for a in list(plan.agents)+list(plan.tie_offs) for fid in a.fact_ids}
    def payload_for(batch):
        ids=common_ids|{fid for item in batch for fid in item['component']['fact_ids']}
        quotes={};selected=[]
        for fid in sorted(ids):
            fact=dict(facts[fid]);key=digest([fact['source_id'],fact['quote']])[:16]
            quotes[key]=fact.pop('quote');fact['quote_reference']=key;selected.append(fact)
        return dict(shared=shared,components=batch,facts=selected,quoted_evidence=quotes)
    batches=[components[i:i+8] for i in range(0,len(components),8)] or [[]]
    problems=[];records=[]
    with Tracer(directory/'trace.jsonl','code_review',metadata={'model':llm.model}) as tracer:
        client=CheckpointLLM(llm,directory/'llm_cache'/'review',stage='code_review')
        while batches:
            batch=batches.pop(0);payload=payload_for(batch)
            if len(json.dumps(payload))>48000:
                if len(batch)<2: raise ValueError('One review component exceeds its scoped context; decompose it')
                middle=len(batch)//2;batches[:0]=[batch[:middle],batch[middle:]];continue
            emit(f'code review: batch {len(records)+1} of {len(records)+len(batches)+1}')
            result=client.structured(name='code_review',instructions='Independently audit these implementation components '
                'against their cited facts and shared foundation. Quotes are stored once in quoted_evidence. '
                'Reject unsupported expectations, protocol bindings, register addresses/data lanes, serial configuration/timing, '
                'unjustified tie-offs, missing checking, races, incorrect scoreboard routing and unsupported FSM implementation. '
                'Other batches are reviewed separately; do not demand components absent from this batch. '
                'Operational testbench limits are not DUT requirements. Return concrete problems; empty only if supported.',
                payload=payload,schema=schema,tracer=tracer)
            problems+=result.data['problems']
            records.append(dict(components=[v['component']['id'] for v in batch],input_chars=len(json.dumps(payload)),
                                problems=result.data['problems'],cached=result.cached))
    atomic_write_text(directory/'contract_review.json',json.dumps(dict(problems=problems,batches=records),indent=2)+'\n')
    if problems: raise ValueError('Contract review: '+'; '.join(problems))


# Model-written hooks may call only these system functions: pure sampling/formatting helpers.
# Anything else ($fdisplay, $writememh, $dumpfile, $finish, $value$plusargs, ...) is refused, not blocklisted.
ALLOWED_SYSTEM_CALLS=frozenset({
    'display','sformatf','cast','time','realtime','isunknown','onehot','onehot0','countones','clog2','bits','size',
    'high','low','left','right','dimensions','signed','unsigned','urandom','urandom_range',
    'past','rose','fell','stable','changed','error','warning','info','typename'})


HOOK_WRAPPER=re.compile(r'\s*(?:task|function)\b[^;]*?\(\s*\)\s*;(.*)\b(?:endtask|endfunction)(?:\s*:\s*\w+)?\s*|\s*task\s+(?:automatic\s+)?\w+\s*;(.*)\bendtask(?:\s*:\s*\w+)?\s*',re.S)


def unwrap_hook(code):
    """The template owns the task or function; a hook is its statements, whichever way the model wrote them."""
    match=HOOK_WRAPPER.fullmatch(code)
    return (match.group(1) or match.group(2) or '') if match else code


def check_hook(code, task, plan):
    code=_checked_code(unwrap_hook(code),task.id)
    if re.search(r'(?m)^\s*(?:task|function|endtask|endfunction)\b',code):
        raise ValueError('A hook is the statements of its body; do not declare a task or function')
    for name in dict.fromkeys(re.findall(r'\$(\w+)',re.sub(r'"(?:\\.|[^"\\])*"','""',code))):
        if name not in ALLOWED_SYSTEM_CALLS:
            raise ValueError(f'Hook uses ${name}, which is not an allowed system function')
    if re.search(r'\$(?:system|fopen|fwrite|readmem\w*)\b|`(?!uvm_(?:fatal|error|warning|info)\b)|\b(?:force|release|bind|uvm_hdl_\w*)\b|\$root|\bp_sequencer\b|\bdut\s*\.',code):
        raise ValueError('Hook contains forbidden external/system/declaration access')
    if task.slot in ('monitor.body','coverage.sample','scoreboard.compare') and re.search(r'cfg\.vif\.\w+\s*(?:<=|=(?!=))',code):
        raise ValueError('Observation hooks cannot drive interface signals')
    if task.slot.endswith(('sample','compare')) and re.search(r'(?<!\w)[#@]|\bwait\s*\(',code):
        raise ValueError('Function hooks cannot consume simulation time')
    return code


def implement(llm, plan, directory, *, compiler_feedback=None):
    if not plan.hooks: return {}
    facts={f.id:f.model_dump() for f in plan.facts}
    schema={'type':'object','additionalProperties':False,'required':['code'], 'properties':{'code':{'type':'string'}}}
    def task(hook):
        path=directory/'hook_cache'/f'{hook.id}-{digest([hook.model_dump(),plan.model_dump(),llm.model])}.json'
        # API checkpoint also keys on template context/instructions/schema; cache files are evidence artifacts.
        feedback=(compiler_feedback or {}).get(hook.id)
        for attempt in range(2):
            with Tracer(directory/'trace.jsonl','code_hook',input={'id':hook.id,'attempt':attempt}) as tracer:
                result=CheckpointLLM(llm,directory/'llm_cache'/'hooks',stage='code_hook').structured(
                name='code_hook',instructions='Implement only this declared SystemVerilog task/function hook from cited facts. '
                'Return only the statements of its body, without a task or function wrapper. '
                'Use cfg.vif canonical roles and cg_item fields. No new classes/modules/includes, external system/file access, '
                'hierarchical DUT access, invented expectations, state-machine reference model or p_sequencer. '
                'Monitor publishes a new cg_item per completed observation on ap. Never mutate received transactions.',
                payload={'task':hook.model_dump(),'facts':[facts[f] for f in hook.fact_ids], 'repair_feedback':feedback,
                         'agent':next((a.model_dump() for a in plan.agents if a.id==hook.target),None),
                         'item_template':(ROOT/'item.svh.tmpl').read_text(),
                         'hook_contract':json.loads((ROOT/'catalog.json').read_text())['hooks'][hook.slot]},
                schema=schema,tracer=tracer)
            try:
                code=check_hook(result.data['code'],hook,plan)
                break
            except ValueError as exc:
                if attempt==1:
                    # A prototype builds without this hook; the agent keeps its default body and the gap is a question.
                    if not (enabled() and (directory/'quick_testing.json').is_file()): raise
                    plan.questions.append(f'Deferred (quick testing): hook {hook.id} was not built: {str(exc)[:240]}')
                    return hook.id,None
                feedback={'previous_code':result.data['code'],'error':str(exc)}
        atomic_write_text(path,json.dumps(dict(id=hook.id,code=code,fact_ids=hook.fact_ids),indent=2)+'\n')
        return hook.id,code
    emit(f'code hooks: 0 of {len(plan.hooks)} done')
    implemented={}
    with ThreadPoolExecutor(max_workers=2) as executor:
        for done,(hook_id,code) in enumerate(executor.map(cancel.bind(task),plan.hooks),1):
            emit(f'code hooks: {done} of {len(plan.hooks)} done')  # from this thread: progress sinks are per thread
            if code is not None: implemented[hook_id]=code
    return implemented

"""Small evidence-backed work packages: dependency notes -> pseudocode -> code IR.

Planning prose guides implementation, but only independently retrieved documented
facts can supply executable expectations. Each API request has its own checkpoint.
"""
import json
from pathlib import Path

from pydantic import Field

from ..ingest.extract import locate_quote
from ..core.fsutil import atomic_write_text
from ..graph.graph_checkpoint import CheckpointLLM
from ..core.progress import emit
from ..retrieval.retrieval import BM25, tokenize
from ..core.trace import Tracer
from .contracts import Model, CodePlan, Fact, Sequence, Route, Check, Hook, Test, CoverageGoal, digest, identifier, pointer
from .reasoning import INSTRUCTIONS, compact_items, eligible_items, strict_schema
from .validate import validate,validate_facts
from .events import stage, skip, feature_steps


class Dependency(Model):
    task_id: str
    reason: str


class WorkTask(Model):
    id: str = Field(max_length=64)
    title: str
    category: str
    goal: str
    plan_pointers: list[str] = Field(min_length=1, max_length=6)
    depends_on: list[Dependency] = Field(default_factory=list)
    queries: list[str] = Field(min_length=1, max_length=3)


class WorkGraph(Model):
    understanding: str
    tasks: list[WorkTask] = Field(min_length=1, max_length=64)
    questions: list[str] = Field(default_factory=list)


class CrossDependency(Model):
    task_id: str
    requires: str
    reason: str


class Collation(Model):
    understanding: str
    dependencies: list[CrossDependency]
    questions: list[str]


class Pseudocode(Model):
    understanding: str
    preconditions: list[str]
    stimulus_steps: list[str]
    check_steps: list[str]
    coverage_steps: list[str]
    completion: list[str]
    facts: list[Fact] = Field(default_factory=list, max_length=32)
    questions: list[str]
    blockers: list[str] = Field(default_factory=list)


class StepImplementation(Model):
    step: str
    component_ids: list[str]
    question: str


class Fragment(Model):
    facts: list[Fact] = Field(default_factory=list, max_length=32)
    sequences: list[Sequence] = Field(default_factory=list, max_length=16)
    routes: list[Route] = Field(default_factory=list, max_length=16)
    checks: list[Check] = Field(default_factory=list, max_length=16)
    hooks: list[Hook] = Field(default_factory=list, max_length=8)
    coverage: list[CoverageGoal] = Field(default_factory=list,max_length=8)
    step_implementations: list[StepImplementation] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class Integration(Model):
    tests: list[Test] = Field(default_factory=list, max_length=64)
    questions: list[str] = Field(default_factory=list)


class ImplementationApproach(Model):
    shared_setup: list[str]
    execution_order: list[list[str]]
    stimulus_approach: list[str]
    check_approach: list[str]
    coverage_approach: list[str]
    questions: list[str]


def inventory(plan):
    """Index intentions, including labeled implementation proposals, without source bodies."""
    entries=[]
    strategy=[]
    for i,section in enumerate(plan.get('sections',[])):
        if section.get('id')=='strategy':
            strategy=[dict(text=e['text'][:600],provenance=e.get('provenance','INFERRED'))
                      for e in section.get('strategy',{}).get('overview',[])]
        if section.get('id') not in ('stimulus','checks','coverage','verification_plan'): continue
        for j,entry in enumerate(section.get('entries',[])):
            if entry.get('cited_rtl_observation_ids'): continue
            entries.append(dict(plan_pointer=f'/sections/{i}/entries/{j}',category=section['id'],
                                kind=entry.get('kind',''),text=entry.get('text','')[:400],
                                provenance=entry.get('provenance','ASSUMED')))
    return entries,strategy


def dependency_waves(graph, known):
    tasks={t.id:t for t in graph.tasks}
    if len(tasks)!=len(graph.tasks): raise ValueError('Duplicate work-package IDs')
    assignments=[]
    for task in graph.tasks:
        identifier(task.id)
        if not set(task.plan_pointers)<=known: raise ValueError('Work package references an unknown plan intention')
        assignments+=task.plan_pointers
        ids=[d.task_id for d in task.depends_on]
        if len(ids)!=len(set(ids)) or not set(ids)<=tasks.keys() or task.id in ids:
            raise ValueError('Invalid work-package dependency')
        if any(not d.reason.strip() for d in task.depends_on): raise ValueError('Dependency requires its reasoning')
    if set(assignments)!=known: raise ValueError('Every plan intention needs a work package; retain unsupported work as questions')
    if len(assignments)!=len(set(assignments)): raise ValueError('Plan intention assigned more than once')
    done=set();waves=[]
    while len(done)<len(tasks):
        ready=sorted(k for k,t in tasks.items() if k not in done and {d.task_id for d in t.depends_on}<=done)
        if not ready: raise ValueError('Cyclic feature dependencies; clarify before code generation')
        waves.append(ready);done.update(ready)
    return waves


class Evidence:
    def __init__(self, plan, sources):
        self.plan,self.sources=plan,sources
        self.items=compact_items(eligible_items(plan,sources),plan)
        self.index=BM25({str(i):tokenize(json.dumps(item['item'])) for i,item in enumerate(self.items)},1.5,0.75)
        self.windows={}
        # Exact bounded windows, never a full source dump. Offsets preserve quotation validation.
        for sid,text in sorted(sources.items()):
            for start in range(0,len(text),1000):
                self.windows[f'{sid}@{start}']=dict(source_id=sid,start=start,end=min(len(text),start+1600),text=text[start:start+1600])
        self.window_index=BM25({k:tokenize(v['text']) for k,v in self.windows.items()},1.5,0.75)

    def fetch(self, queries, source_ids=(), *, item_limit=16, focus=False):
        query=tokenize(' '.join(queries))
        scores=self.index.score(query)
        ranked=sorted(range(len(self.items)),key=lambda i:(-scores.get(str(i),0),self.items[i]['plan_pointer']))
        selected=[self.items[i] for i in ranked[:item_limit] if scores.get(str(i),0)>0]
        wanted=set(source_ids)|{sid for item in selected for sid in item['source_ids']}
        ranks=self.window_index.score(query)
        direct=set(source_ids)
        def rank(key):
            priority=0 if self.windows[key]['source_id'] in direct else 1 if self.windows[key]['source_id'] in wanted else 2
            return (-ranks.get(key,0),priority,key) if focus else (priority,-ranks.get(key,0),key)
        ordered=sorted(self.windows,key=rank)
        windows=[];per_source={}
        for key in ordered:
            w=self.windows[key]
            if not ranks.get(key,0) and w['source_id'] not in wanted: continue
            if per_source.get(w['source_id'],0)>=2: continue
            windows.append(w);per_source[w['source_id']]=per_source.get(w['source_id'],0)+1
            if len(windows)==8: break
        return dict(documented_items=selected,source_excerpts=windows,
                    available_source_ids=sorted(wanted),retrieval_queries=queries,focused_recovery=focus)


def _facts_in_context(facts, context):
    allowed={i['plan_pointer'] for i in context['documented_items']}
    for fact in facts:
        if fact.plan_pointer not in allowed: raise ValueError('Fact must reference a retrieved documented item')
        if not any(w['source_id']==fact.source_id and locate_quote(w['text'],fact.quote) is not None
                   for w in context['source_excerpts']):
            raise ValueError('Fact quote must occur in a retrieved source excerpt')


def _pseudocode_problems(pseudo, categories):
    """Questions preserve gaps; they cannot substitute for an implementation."""
    problems=[]
    for key in ('understanding',):
        if not getattr(pseudo,key).strip(): problems.append('Missing '+key)
    for key in ('preconditions','stimulus_steps','check_steps','coverage_steps','completion','questions','blockers'):
        if any(not text.strip() for text in getattr(pseudo,key)): problems.append('Blank text in '+key)
    if not any((pseudo.stimulus_steps,pseudo.check_steps,pseudo.coverage_steps)):
        problems.append('Feature needs actionable pseudocode; questions alone are not implementation steps')
    for category,key in (('stimulus','stimulus_steps'),('checks','check_steps'),('coverage','coverage_steps')):
        if category in categories and not getattr(pseudo,key): problems.append('Assigned '+category+' intention needs '+key)
    if not pseudo.completion: problems.append('Missing bounded completion/termination criteria')
    if not pseudo.facts: problems.append('Missing documented supporting facts for actionable pseudocode')
    if pseudo.blockers: problems.append('Essential evidence blockers: '+'; '.join(pseudo.blockers))
    return problems


def _approach_check(approach, tasks, feature_ids):
    seen=set()
    known=set(feature_ids)
    for wave in approach.execution_order:
        if not wave or len(wave)!=len(set(wave)) or not set(wave)<=known or seen & set(wave):
            raise ValueError('Collated pseudocode must include every feature exactly once')
        if any(not ({d.task_id for d in tasks[tid].depends_on} & known)<=seen for tid in wave):
            raise ValueError('Collated pseudocode violates feature dependencies')
        seen.update(wave)
    if seen!=known: raise ValueError('Collated pseudocode omitted a feature')
    for key in ('shared_setup','stimulus_approach','check_approach','coverage_approach'):
        values=getattr(approach,key)
        if not values or any(not text.strip() for text in values):
            raise ValueError('Collated pseudocode needs nonempty '+key+'; explain any inapplicable area explicitly')


def _collate(call, strategy, tasks, pseudocode):
    """Hierarchical collation preserves actual steps without a whole-plan prompt."""
    features={tid:{key:value for key,value in p.model_dump().items() if key!='facts'} for tid,p in pseudocode.items()}
    nodes=[dict(feature_ids=[tid],features={tid:data}) for tid,data in features.items()]
    rules=('Collate supplied actual feature steps into cohesive language-neutral implementation pseudocode. '
           'Preserve supported actions, preconditions, completion criteria and unresolved questions. '
           'Provide nonempty shared_setup, stimulus_approach, check_approach and coverage_approach: '
           'describe reusable setup, producer/consumer paths, sequence composition, monitor/check/scoreboard '
           'relationships and monitor sampling. Explicitly explain an inapplicable area rather than leaving it empty. '
           'No new DUT behavior or expected values, no SystemVerilog. Include each feature exactly once in '
           'execution_order; honor dependencies within this batch. External dependencies are handled at final collation. '
           'This is generation order, not permission for concurrent DUT traffic.')

    def payload(group, level):
        ids=[tid for node in group for tid in node['feature_ids']]
        return dict(high_level_strategy=strategy,level=level,
                    dependencies=[dict(id=tid,requires=[d.task_id for d in tasks[tid].depends_on]) for tid in ids],
                    features={tid:data for node in group for tid,data in node.get('features',{}).items()},
                    collated_groups=[node for node in group if 'approach' in node])

    for level in range(8):
        groups=[];group=[]
        for node in nodes:
            if group and len(json.dumps(payload(group+[node],level)))>32000:
                groups.append(group);group=[]
            group.append(node)
        if group: groups.append(group)
        reduced=[]
        for batch,group in enumerate(groups):
            data=payload(group,level);data['batch']=batch
            ids=[tid for node in group for tid in node['feature_ids']]
            approach=call('code_collation',data,ImplementationApproach,rules,
                          lambda result: _approach_check(result,tasks,ids))
            reduced.append(dict(feature_ids=ids,approach=approach.model_dump()))
        if len(reduced)==1: return approach
        if level and len(reduced)>=len(nodes):
            raise ValueError('Collated summaries exceed context budget; split feature work rather than discarding steps')
        nodes=reduced
    raise ValueError('Collation exceeded bounded reduction depth')


def _merge(plan, fragment):
    data=plan.model_dump()
    for key,values in fragment.model_dump().items():
        if key=='step_implementations': continue
        if key=='questions':
            data[key]=list(dict.fromkeys(data[key]+values));continue
        existing={item['id']:item for item in data[key]}
        for item in values:
            if item['id'] in existing and existing[item['id']]!=item:
                raise ValueError(f'Conflicting {key} identifier {item["id"]}; namespace new IDs by work package')
            existing[item['id']]=item
        data[key]=list(existing.values())
    return CodePlan.model_validate(data)


def _write(path, value):
    text=json.dumps(value,indent=2,default=str)+'\n'
    if path.parent.parent.name=='code_work': _artifact(path,text)
    else: atomic_write_text(path,text)


def _artifact(path,text):
    if path.exists() and path.read_text()!=text:
        raise ValueError('Work document was edited; preserve the revision before regenerating: '+path.name)
    if not path.exists(): atomic_write_text(path,text)


def _document(task, pseudo, independent):
    lines=[f'# {task.title}', '', f'Work package: `{task.id}` · {task.category} · NEEDS_REVIEW','',
           '## Dependent features','']
    lines += [f'- `{d.task_id}`: {d.reason}' for d in task.depends_on] or ['- None identified.']
    lines += ['', '## Independent features','', ', '.join(f'`{i}`' for i in independent) or 'None identified.',
              '', '_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._','',
              '## Understanding','',pseudo.understanding,'']
    for title,key in [('Preconditions','preconditions'),('Stimulus pseudocode','stimulus_steps'),
                      ('Check pseudocode','check_steps'),('Coverage pseudocode','coverage_steps'),('Completion','completion'),('Questions','questions'),('Essential blockers','blockers')]:
        lines += ['## '+title,'']
        steps=[f'{i}. {text}' for i,text in enumerate(getattr(pseudo,key),1)]
        lines += (['```text']+steps+['```'] if key.endswith('_steps') else steps)+['']
    lines += ['## Specification evidence','']
    for fact in pseudo.facts: lines += [f'- `{fact.id}` → `{fact.plan_pointer}` / `{fact.source_id}`', '> '+fact.quote.replace('\n','\n> '),'']
    return '\n'.join(lines)


def design(llm, plan, definition, sources, directory, *, previous=None, feedback=None,pseudocode_only=False):
    """Generate one foundation and feature fragments, not a whole-document request."""
    if plan.get('source_authority')=='RTL_INFERRED': raise ValueError('Unvalidated RTL-derived expectations are not executable')
    intentions,strategy=inventory(plan)
    if not intentions: raise ValueError('No stimulus/check/coverage implementation intentions in saved plan')
    directory=Path(directory)
    work=directory/'code_work'/digest([plan,definition,llm.model,INSTRUCTIONS,Path(__file__).read_text(),feedback])[:16]
    work.mkdir(parents=True,exist_ok=True)
    evidence=Evidence(plan,sources)
    client=CheckpointLLM(llm,directory/'llm_cache'/'code_work',stage='code_work')
    records=[]
    work_manifest=dict(work_dir=str(work),status='IN_PROGRESS',pseudocode_tasks=[],completed_tasks=[],
                       tasks=[],review_status='NEEDS_REVIEW',
                       quality_policy='actionable_source_backed_features_and_complete_collation')
    _write(directory/'code_work_manifest.json',work_manifest)
    with Tracer(directory/'trace.jsonl','code_work',metadata={'model':llm.model}) as tracer:
        def request(name,payload,model,rules,check=lambda result:None,recover=None):
            issue=None
            for attempt in range(2):
                if len(json.dumps(payload))>48000: raise ValueError(f'{name}: work package too large; split this package')
                emit(f'code work: {name}, {len(json.dumps(payload))} characters'+(' (repair)' if attempt else ''))
                result=client.structured(name=name,instructions=INSTRUCTIONS+'\n'+rules,payload=payload,
                                         schema=strict_schema(model),tracer=tracer)
                try:
                    typed=model.model_validate(result.data);check(typed)
                except ValueError as exc:
                    issue=dict(stage=name,attempt=attempt+1,status='BLOCKED' if attempt else 'REPAIR_PENDING',
                               task_id=payload.get('task',{}).get('id'),reason=str(exc),rejected_output=result.data)
                    _write(directory/'code_planning_issue.json',issue)
                    if attempt: raise
                    payload=payload|dict(repair_feedback=str(exc))
                    if recover is not None: payload=recover(payload,result.data,str(exc))
                    continue
                records.append(dict(stage=name,input_chars=len(json.dumps(payload)),cached=result.cached))
                if issue:
                    _write(directory/'code_planning_issue.json',issue|dict(status='RECOVERED'))
                _write(directory/'code_context.json',dict(mode='feature_work_packages',requests=records,
                       max_request_chars=max(r['input_chars'] for r in records),work_dir=str(work)))
                return typed

        def call(name,payload,model,rules,check=lambda result:None,recover=None):
            sid=name
            label=None
            if name=='code_pseudocode':
                sid+=':'+payload['task']['id']
                label='Understand '+payload['task']['title']
            elif name=='code_feature':
                sid+=':'+payload['task_id']
                label='Implement '+tasks[payload['task_id']].title
            with stage(sid,label) as outcome:
                try:
                    result=request(name,payload,model,rules,check,recover)
                except (Exception,KeyboardInterrupt) as exc:
                    if work_manifest is not None:
                        work_manifest.update(status='BLOCKED',blocked_stage=sid,
                                             reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
                        _write(directory/'code_work_manifest.json',work_manifest)
                    raise
                outcome['reused']=records[-1]['cached']
                return result

        def graph_check(g): dependency_waves(g,{i['plan_pointer'] for i in intentions})
        batches=[];batch=[]
        for intention in intentions:
            if batch and len(json.dumps(batch+[intention]))>20000:
                batches.append(batch);batch=[]
            batch.append(intention)
        if batch: batches.append(batch)
        graphs=[];used=set()
        for index,batch in enumerate(batches):
            def batch_check(g):
                dependency_waves(g,{i['plan_pointer'] for i in batch})
                if used & {t.id for t in g.tasks}: raise ValueError('Work IDs must not collide with earlier batches')
            g=call('code_grouping',dict(high_level_strategy=strategy,intentions=batch,batch=index,existing_task_ids=sorted(used)),WorkGraph,
                'Group similar plan intentions into cohesive feature work packages (at most six pointers each). '
                'Include every supplied intention exactly once, including unsupported ones as review work. Identify '
                'within-batch dependent features with reasons; cross-batch dependencies will be collated afterward. '
                'Use unique IDs. No dependency merely because items are adjacent. These are implementation proposals.',batch_check)
            graphs.append(g);used.update(t.id for t in g.tasks)
        graph=WorkGraph(understanding='\n'.join(g.understanding for g in graphs),tasks=[t for g in graphs for t in g.tasks],
                        questions=[q for g in graphs for q in g.questions])
        if len(graphs)>1:
            def collation_check(c):
                candidate=graph.model_copy(deep=True);by_id={t.id:t for t in candidate.tasks}
                for dep in c.dependencies:
                    if dep.task_id not in by_id or dep.requires not in by_id: raise ValueError('Unknown cross-batch dependency')
                    if dep.requires not in {d.task_id for d in by_id[dep.task_id].depends_on}:
                        by_id[dep.task_id].depends_on.append(Dependency(task_id=dep.requires,reason=dep.reason))
                graph_check(candidate)
            collated=call('code_dependencies',dict(high_level_strategy=strategy,tasks=[dict(id=t.id,title=t.title,goal=t.goal,
                depends_on=[d.model_dump() for d in t.depends_on]) for t in graph.tasks]),Collation,
                'Collate feature understanding across batches. Add genuine cross-feature dependencies with reasons '
                'without changing task scope or inventing expected behavior. No source documents are supplied here.',collation_check)
            by_id={t.id:t for t in graph.tasks}
            for dep in collated.dependencies:
                if dep.requires not in {d.task_id for d in by_id[dep.task_id].depends_on}:
                    by_id[dep.task_id].depends_on.append(Dependency(task_id=dep.requires,reason=dep.reason))
            graph.understanding=collated.understanding;graph.questions+=collated.questions
        graph_check(graph)
        waves=dependency_waves(graph,{i['plan_pointer'] for i in intentions})
        tasks={t.id:t for t in graph.tasks}
        feature_steps(waves,tasks)
        if len(graphs)==1: skip("code_dependencies")
        ancestors={}
        for wave in waves:
            for tid in wave: ancestors[tid]={d.task_id for d in tasks[tid].depends_on}|{a for d in tasks[tid].depends_on for a in ancestors[d.task_id]}
        independent={tid:sorted(t for t in tasks if t!=tid and t not in ancestors[tid] and tid not in ancestors[t]) for tid in tasks}
        _write(work/'dependencies.json',dict(**graph.model_dump(),generation_waves=waves,independent=independent,
                                            dependency_authority='INFERRED_IMPLEMENTATION_ORDER',review_status='NEEDS_REVIEW'))
        _artifact(work/'DEPENDENCIES.md','# Feature dependency plan\n\n'+graph.understanding+'\n\n'+
            '\n'.join(f'- **{t.id}**: depends on '+(', '.join(d.task_id for d in t.depends_on) or 'none')+
                      '; independent of '+(', '.join(independent[t.id]) or 'none') for t in graph.tasks)+
            '\n\n_Implementation planning requires review; independence does not imply safe parallel DUT traffic._\n')
        work_manifest=dict(work_dir=str(work),generation_waves=waves,pseudocode_tasks=[],completed_tasks=[],status='IN_PROGRESS',
            tasks=[dict(id=t.id,document=str(work/(t.id+'.md')),pseudocode=str(work/(t.id+'.pseudocode.json'))) for t in graph.tasks],
            review_status='NEEDS_REVIEW',quality_policy='actionable_source_backed_features_and_complete_collation')
        _write(directory/'code_work_manifest.json',work_manifest)

        completed={};pseudocode_by_id={};contexts={}
        for wave in waves:
            for tid in wave:
                task=tasks[tid]
                emit(f'code feature {tid}: retrieve excerpts, write pseudocode, implement scoped components')
                targets=[]
                for p in task.plan_pointers:
                    entry=pointer(plan,p)
                    targets.append(dict(plan_pointer=p,**{k:entry[k] for k in
                        ('text','details','kind','provenance','cited_chunk_ids','cited_req_ids') if k in entry}))
                direct={sid for target in targets for sid in target.get('cited_chunk_ids',[])+target.get('cited_req_ids',[])}
                selected=evidence.fetch(task.queries+[task.goal]+[t['text'] for t in targets],source_ids=direct)
                payload=dict(task=task.model_dump(),planning_intentions=targets,high_level_strategy=strategy,
                             dependencies={d.task_id:completed[d.task_id] for d in task.depends_on},
                             interface=definition,evidence=selected)
                _write(work/(tid+'.context.json'),payload)
                categories={intent['category'] for intent in intentions if intent['plan_pointer'] in task.plan_pointers}
                def pseudo_check(p):
                    _facts_in_context(p.facts,selected)
                    validate_facts(p.facts,plan,sources)
                    problems=_pseudocode_problems(p,categories)
                    if problems: raise ValueError('; '.join(problems))

                def recover_pseudo(retry,rejected,reason):
                    nonlocal selected
                    previous=rejected if isinstance(rejected,dict) else {}
                    gaps=[q for key in ('blockers','questions') for q in
                          (previous.get(key,[]) if isinstance(previous.get(key,[]),list) else []) if isinstance(q,str)]
                    queries=gaps[:8]+task.queries+[task.goal]
                    selected=evidence.fetch(queries,source_ids=direct,focus=True)
                    emit(f'code feature {tid}: recover evidence for incomplete pseudocode')
                    retry=retry|dict(evidence=selected,previous_pseudocode={k:v for k,v in previous.items() if k!='facts'})
                    _write(work/(tid+'.recovery.context.json'),retry)
                    return retry

                pseudo=call('code_pseudocode',payload,Pseudocode,
                    'This is feature planning, not the final runnable CodePlan: retain supported partial algorithms '
                    'even when other features or final bus bindings need clarification. Do not require a complete '
                    'register map or all protocol settings to plan a supported monitor/check/coverage feature. '
                    'Collate this feature and its dependencies into precise language-neutral pseudocode: '
                    'preconditions, stimulus steps, comparisons/checks, monitor-sampled coverage and bounded completion. '
                    'Provide steps for each assigned stimulus/checks/coverage intention; unused categories may be empty. '
                    'Use algorithmic IF/FOR/WAIT/SAMPLE/COMPARE steps with termination and cleanup. '
                    'Testbench timeouts are operational limits, not DUT requirements. '
                    'Supply exact documented facts for behavior; INFERRED/ASSUMED intentions guide architecture only. '
                    'Use symbolic references to supported settings if concrete bindings are unresolved, without inventing values. '
                    'Questions record missing or ambiguous details; blockers list ONLY essential gaps preventing ALL supported '
                    'work in this feature. Questions alone are not pseudocode. Inspect supplied documented items and excerpts '
                    'before asking for information already present. On repair use recovered excerpts to resolve gaps, retaining '
                    'supported work. Never invent expected behavior to fill a required list. Do not emit SystemVerilog.',
                    pseudo_check,recover_pseudo)
                _write(work/(tid+'.pseudocode.json'),pseudo.model_dump())
                _artifact(work/(tid+'.md'),_document(task,pseudo,independent[tid]))
                completed[tid]=dict(understanding=pseudo.understanding,completion=pseudo.completion,
                                    questions=pseudo.questions)
                pseudocode_by_id[tid]=pseudo;contexts[tid]=selected
                work_manifest['pseudocode_tasks'].append(tid)
                _write(directory/'code_work_manifest.json',work_manifest)
        try:
            approach=_collate(call,strategy,tasks,pseudocode_by_id)
        except ValueError as exc:
            work_manifest.update(status='BLOCKED',blocked_stage='code_collation',reason=str(exc))
            _write(directory/'code_work_manifest.json',work_manifest)
            raise
        _write(work/'COLLATED_PSEUDOCODE.json',approach.model_dump())
        _artifact(work/'COLLATED_PSEUDOCODE.md','# Collated implementation pseudocode\n\n'+
            '\n'.join(f'- Stage {i+1}: '+', '.join(stage) for i,stage in enumerate(approach.execution_order))+'\n\n'+
            '\n\n'.join('## '+key.replace('_',' ').title()+'\n\n'+'\n'.join('- '+v for v in getattr(approach,key))
                for key in ('shared_setup','stimulus_approach','check_approach','coverage_approach','questions'))+'\n')
        work_manifest['status']='PSEUDOCODE_READY_NEEDS_REVIEW'
        _write(directory/'code_work_manifest.json',work_manifest)
        if pseudocode_only: return work_manifest
        context=evidence.fetch(['clock reset polarity interface protocol input output integration configuration register address access'],item_limit=24)
        foundation_payload=dict(interface=definition,high_level_strategy=strategy,collated_pseudocode=approach.model_dump(),evidence=context)
        if feedback: foundation_payload['repair_feedback']=feedback
        def foundation_check(p):
            if p.sequences or p.routes or p.checks or p.tests or p.coverage: raise ValueError('Foundation must not implement feature tests/checks/sequences/coverage')
            _facts_in_context(p.facts,context);validate(p,plan,definition,sources)
        foundation=call('code_foundation',foundation_payload,CodePlan,
            'Generate ONLY shared wiring/configuration/agents, explicit input ownership, simple register mirrors and '
            'required custom driver/monitor hook declarations from collated pseudocode. Empty sequences/routes/checks/tests. '
            'Use only retrieved DOCUMENTED facts; proposed strategy is guidance, not an expectation source.',foundation_check)
        _write(work/'foundation.json',foundation.model_dump())
        assembled=foundation
        assembled.questions=list(dict.fromkeys(assembled.questions+approach.questions))
        for wave in approach.execution_order:
            for tid in wave:
                task=tasks[tid];pseudo=pseudocode_by_id[tid];selected=contexts[tid]
                # Only this pseudocode, its excerpts and shared API signatures go to coding.
                coding=dict(task_id=tid,pseudocode=pseudo.model_dump(),shared_agents=[a.model_dump() for a in foundation.agents],
                            collated_approach=approach.model_dump(),
                            shared_registers=[r.model_dump() for r in foundation.registers],
                            builtin_coverage=[a.id+'_coverage' for a in foundation.agents],
                            dependency_components=[dict(task_id=d.task_id,**completed[d.task_id]) for d in task.depends_on],
                            evidence=selected)
                def fragment_check(f):
                    _facts_in_context(f.facts,selected)
                    validate(_merge(assembled,f),plan,definition,sources)
                    mapped=[m.step for m in f.step_implementations]
                    expected={key+'/'+str(i) for key in ('stimulus_steps','check_steps','coverage_steps')
                              for i in range(len(getattr(pseudo,key)))}
                    if set(mapped)!=expected or len(mapped)!=len(set(mapped)):
                        raise ValueError('Every pseudocode step needs exactly one implementation mapping or explicit question')
                    allowed={s.id for s in f.sequences}|{c.id for c in f.checks}|{r.id for r in f.routes}|{h.id for h in f.hooks}
                    allowed|={r.id for r in foundation.registers}|{c.id for c in f.coverage}|{a.id+'_coverage' for a in foundation.agents}
                    for mapping in f.step_implementations:
                        if bool(mapping.component_ids)==bool(mapping.question.strip()):
                            raise ValueError('A pseudocode step must be implemented or explicitly deferred with a question')
                        if not set(mapping.component_ids)<=allowed: raise ValueError('Step mapping references an unknown component')
                fragment=call('code_feature',coding,Fragment,
                    f'Implement ONLY work package {tid} from its saved pseudocode. Return reusable typed operations, '
                    'sequence/check/scoreboard declarations and declared coverage hooks, not raw framework code. '
                    'Use existing agent names; namespace NEW IDs with this task ID. facts must include every new '
                    'supporting fact. Do not redefine agents or silently omit unsupported steps: put them in questions. '
                    'Map EVERY stimulus_steps/N, check_steps/N and coverage_steps/N to emitted component_ids or an explicit '
                    'question, never both. Use typed coverage goals for specific bins/crosses over cg_item fields; '
                    'builtin coverage references apply only where its existing bins actually meet the goal. '
                    'Coverage must subscribe to observed monitor transactions. Do not invent expected behavior.',fragment_check)
                assembled=_merge(assembled,fragment)
                _write(work/(tid+'.fragment.json'),fragment.model_dump())
                completed[tid]['sequences']=[s.id for s in fragment.sequences]
                completed[tid]['checks']=[c.id for c in fragment.checks]
                completed[tid]['routes']=[r.id for r in fragment.routes]
                completed[tid]['coverage']=[c.id for c in fragment.coverage]
                assembled.questions=list(dict.fromkeys(assembled.questions+pseudo.questions))
                assembled.questions=list(dict.fromkeys(assembled.questions+[
                    tid+': '+m.question for m in fragment.step_implementations if m.question.strip()]))
                work_manifest['completed_tasks'].append(tid)
                _write(directory/'code_work_manifest.json',work_manifest)
        # Collate interfaces and completed component signatures, never all specification text.
        integration_payload=dict(understanding=graph.understanding,dependency_waves=approach.execution_order,
            collated_pseudocode=approach.model_dump(),
            components=completed,agents=[dict(id=a.id,protocol=a.protocol) for a in assembled.agents],
            sequences=[dict(id=s.id,agent=s.agent,purpose=s.purpose,fact_ids=s.fact_ids) for s in assembled.sequences],
            available_fact_ids=[f.id for f in assembled.facts])
        def integration_check(i):
            validate(_merge(assembled,i),plan,definition,sources)
            owners={}
            for tid,component in completed.items():
                for sid in component.get('sequences',[]): owners.setdefault(sid,set()).add(tid)
            for test in i.tests:
                seen=set()
                for stage in test.stages:
                    for sid in stage:
                        if len(owners.get(sid,set()))!=1: continue  # shared reusable sequence; its role is reviewed in pseudocode
                        tid=next(iter(owners[sid]))
                        for dep in ancestors[tid]:
                            required=set(completed[dep].get('sequences',[]))
                            if required and not seen & required:
                                raise ValueError(f'Test {test.id} starts {tid} before dependency {dep}')
                    seen.update(stage)
        integration=call('code_integration',integration_payload,Integration,
            'Collate completed feature pseudocode/components into cohesive tests. Respect feature dependency order '
            'and explicit setup before dependent traffic. Select one basic test first and additional supported tests. '
            'Virtual sequences spawn only; no concurrent sequences on one agent sequencer. Use only available fact IDs. '
            'Do not invent new expected behavior; unsupported or unresolved flows are questions.',integration_check)
        assembled=_merge(assembled,integration)
        assembled.questions=list(dict.fromkeys(assembled.questions+graph.questions))
        _write(work/'collated_understanding.json',dict(dependencies=graph.model_dump(),components=completed,
                                                     integration=integration.model_dump()))
        _artifact(work/'COLLATED_UNDERSTANDING.md','# Collated implementation understanding\n\n'+graph.understanding+'\n\n'+
            '\n\n'.join(f'## {tid}\n\n{completed[tid]["understanding"]}\n\n[Detailed pseudocode]({tid}.md)' for wave in waves for tid in wave))
        work_manifest['status']='COMPLETE_NEEDS_REVIEW'
        _write(directory/'code_work_manifest.json',work_manifest)
        return assembled

"""The quick-testing reply reads like a reply to the question, not a prompt or a data dump."""
from dv_agent.quality.human_dialogue import describe
from dv_agent.quality.review_display import compose_reply, show_response

REQUEST = {'question': 'Is wb_rst_i asserted high (1) or low (0)?'}
BINDINGS = {'reset_active': 'high', 'reset_cycles': 4}


def shown(**kw):
    lines = []
    body = show_response(lines.append, REQUEST, BINDINGS, 'The spec does not say, so I took the usual choice.', ['Assumed high.'], **kw)
    return '\n'.join(lines), body


def test_the_generated_answer_is_shown_as_a_reply_to_the_question_then_what_it_sets():
    text, body = shown(reply='I would hold reset active high for four cycles. The spec is silent, so this is the common choice; I am not sure about the length.')
    assert text.index('Is wb_rst_i asserted high') < text.index('Reply (generated for quick testing, not from a person)')
    assert 'I would hold reset active high for four cycles.' in text
    assert text.index('I would hold reset') < text.index('This sets') < text.index('Assumptions I made')
    assert 'Reset asserted level: high' in text and '- Assumed high.' in text
    for form_label in ('Reasoning', 'Generated response', 'automated inference', 'QUICK-TEST'):
        assert form_label not in text  # no report headings or labels in the reply itself


def test_without_a_model_written_reply_the_settings_become_a_plain_sentence():
    spoken = compose_reply(BINDINGS, 'The spec does not say.')
    assert spoken.startswith('I would set it like this: ') and 'Reset asserted level: high.' in spoken
    assert spoken.endswith('The spec does not say.') and '\n' not in spoken and '- ' not in spoken
    text, _ = shown(reply='')
    assert 'I would set it like this:' in text


def test_nothing_is_approved_when_no_reply_could_be_produced():
    lines = []
    body = show_response(lines.append, REQUEST, {}, '', [], valid=False)
    assert body == 'No reply could be produced for this request, so nothing was approved.'
    assert 'Is wb_rst_i asserted high' in lines[0]


def test_quick_testing_does_not_promise_a_confirmation_that_never_happens():
    from dv_agent.quality.human_dialogue import format_review
    request = dict(question='Which reset input?', ports=[], unit='foundation_reset', blockers=['Which reset input?'], evidence={})
    quick = format_review(request, quick_test=True)
    assert 'answered automatically for quick testing; no person is asked' in quick
    assert 'Reply in your own words' not in quick and 'I will restate the binding' not in quick and 'Your decision' not in quick
    assert '## How this is answered' in format_review(request, markdown=True, quick_test=True)
    normal = format_review(request)
    assert 'Reply in your own words' in normal and 'I will restate the binding' in normal

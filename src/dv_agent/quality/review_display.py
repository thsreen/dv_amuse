"""Readable review presentation for terminal recordings; never grants approval."""
import math
import os
import time
from contextlib import contextmanager

from ..core.progress import emit_event


def pause_seconds():
    value=float(os.getenv('DV_HITL_DEMO_PAUSE_SECONDS','2'))
    if not math.isfinite(value) or not 0<=value<=60:
        raise ValueError('DV_HITL_DEMO_PAUSE_SECONDS must be between 0 and 60')
    return value


@contextmanager
def presentation():
    # The dashboard continues recording progress, but must not erase the question/answer.
    emit_event('review_presentation_start')
    try: yield
    finally: emit_event('review_presentation_end')


def pause(show, *, sleep=time.sleep):
    seconds=pause_seconds()
    if seconds:
        show(f'Continuing in {seconds:g} seconds…')
        emit_event('review_presentation_pause',seconds=seconds)
        sleep(seconds)


def compose_reply(bindings, reason):
    """A plain-English reply from the decided settings, for when the evaluator gave none."""
    from .human_dialogue import describe
    settings = describe(bindings).replace('\n  - ', '; ').replace('\n- ', '\n').splitlines()
    spoken = 'I would set it like this: ' + ' '.join(line.lstrip('- ').rstrip('.') + '.' for line in settings if line.strip())
    return (spoken + ' ' + reason.strip()).strip()


def show_response(show, request, bindings, reason, assumptions, *, valid=True, reply=''):
    """Show the generated answer as a reply to the question, then exactly what it sets. Never an approval."""
    from .human_dialogue import describe
    if valid:
        body = '\n'.join(['Reply (generated for quick testing, not from a person)', '',
                          (reply or '').strip() or compose_reply(bindings, reason), '',
                          'This sets', describe(bindings), '', 'Assumptions I made',
                          *(['- ' + value for value in assumptions] or ['- None.'])])
    else:
        body = 'No reply could be produced for this request, so nothing was approved.'
    show('\nQuestion\n' + request['question'] + '\n\n' + body)
    return body

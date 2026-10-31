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


def show_response(show, request, bindings, reason, assumptions, *, valid=True):
    from .human_dialogue import describe
    title='Generated response — QUICK TESTING ONLY' if valid else 'Generated response — NOT APPROVED'
    body='\n'.join([title,describe(bindings) if bindings else 'No valid binding was proposed.',
                    '', 'Reasoning',reason,'','Assumptions',
                    *(['- '+value for value in assumptions] or ['- None stated.']),
                    '', 'This is an automated inference, not a human approval.'])
    show('\nQuestion\n'+request['question']+'\n\n'+body)
    return body

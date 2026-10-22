"""A previous episode's transport failure must not disarm the next Ford MAIN arm.

Ford MAIN off is a no-entry state: the axis is idle and reports no native ACK,
so the ordinary healthy unlatched baseline never forms. A Mach-E commonly goes
from MAIN off to engaged in one frame, so the first latched frame of the new
arm used to see the stale failure and disarm it.
"""

import pytest

from openpilot.starpilot.tests.test_ford_reverse_intent import NOW, PRODUCER, baseline, change, sample


def fail_episode(cp, cs, f):
  sm, _ = sample(cp, NOW + 10_000_000, NOW + 10_000_000, 2)
  change(sm, 'aolAxisState', lambda a: setattr(a, 'faultReason', 'critical'))
  assert f.observe(sm, cp, cs, NOW + 10_000_000, latched=True, intent_producer_session=PRODUCER)
  assert f.failed


def main_off_idle(cp, cs, f, stamp, sequence, *, main=False, latched=False, native_lateral=False, **axis):
  cs.cruiseState.available = main
  cs.cruiseState.enabled = False
  sm, _ = sample(cp, stamp, stamp, sequence, active=False, requested=native_lateral, allowed=native_lateral)

  def idle(a):
    for name, value in {'nativeAcknowledged': False, **axis}.items():  # no-entry while MAIN is off
      setattr(a, name, value)
  change(sm, 'aolAxisState', idle)
  return f.observe(sm, cp, cs, stamp, latched=latched, intent_producer_session=PRODUCER)


def main_on_arm(cp, cs, f, stamp, sequence):
  cs.cruiseState.available = cs.cruiseState.enabled = True
  sm, _ = sample(cp, stamp, stamp, sequence, active=False, requested=False, allowed=False)

  def requested(a):
    a.desiredLateral = True  # host requests LAT; native has not answered yet
  change(sm, 'aolAxisState', requested)
  return f.observe(sm, cp, cs, stamp, latched=True, intent_producer_session=PRODUCER)


def test_main_off_idle_clears_previous_failure_before_next_arm():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3)
  assert not f.failed and not f.session
  assert not main_on_arm(cp, cs, f, NOW + 30_000_000, 4)


def test_idle_requires_no_requested_axis():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3, desiredLateral=True)
  assert f.failed
  assert main_on_arm(cp, cs, f, NOW + 30_000_000, 4)


@pytest.mark.parametrize('reason', ('transportPause', 'availabilityPause'))
def test_idle_requires_no_fault_reason(reason):
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3, faultReason=reason)
  assert f.failed


def test_idle_requires_the_same_intent_producer():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3, intentProducerSessionId='another-card')
  assert f.failed


def test_latched_failure_is_still_fail_closed():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  # Without an unlatched idle frame the stale failure keeps the existing behavior.
  assert main_on_arm(cp, cs, f, NOW + 30_000_000, 4)


def test_unlatched_main_on_idle_frame_before_the_arm_also_clears():
  # Logged Mach-E: the first MAIN-on frame is still unlatched with the axis idle.
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3, main=True)
  assert not f.failed


def test_latched_idle_frame_is_still_fail_closed():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  assert main_off_idle(cp, cs, f, NOW + 20_000_000, 3, latched=True)
  assert f.failed


def test_idle_requires_axis_mode_off():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3, mode='lateralOnly')
  assert f.failed


def test_idle_requires_native_lateral_dropped():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3, native_lateral=True)
  assert f.failed

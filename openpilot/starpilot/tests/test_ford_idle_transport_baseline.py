"""A previous episode's transport failure must not disarm the next Ford MAIN arm.

Ford MAIN off is a no-entry state: the axis is idle and reports no native ACK,
so the ordinary healthy unlatched baseline never forms. A Mach-E commonly goes
from MAIN off to engaged in one frame, so the first latched frame of the new
arm used to see the stale failure and disarm it.
"""

from openpilot.starpilot.tests.test_ford_reverse_intent import NOW, PRODUCER, baseline, change, sample


def fail_episode(cp, cs, f):
  sm, _ = sample(cp, NOW + 10_000_000, NOW + 10_000_000, 2)
  change(sm, 'aolAxisState', lambda a: setattr(a, 'faultReason', 'critical'))
  assert f.observe(sm, cp, cs, NOW + 10_000_000, latched=True, intent_producer_session=PRODUCER)
  assert f.failed


def main_off_idle(cp, cs, f, stamp, sequence, *, desired=False):
  cs.cruiseState.available = cs.cruiseState.enabled = False
  sm, _ = sample(cp, stamp, stamp, sequence, active=False, requested=False, allowed=False)

  def idle(a):
    a.nativeAcknowledged = False  # no-entry while MAIN is off
    a.desiredLateral = desired
  change(sm, 'aolAxisState', idle)
  f.observe(sm, cp, cs, stamp, latched=False, intent_producer_session=PRODUCER)


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
  main_off_idle(cp, cs, f, NOW + 20_000_000, 3, desired=True)
  assert f.failed
  assert main_on_arm(cp, cs, f, NOW + 30_000_000, 4)


def test_idle_requires_no_fault_reason():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  cs.cruiseState.available = cs.cruiseState.enabled = False
  sm, _ = sample(cp, NOW + 20_000_000, NOW + 20_000_000, 3, active=False, requested=False, allowed=False)

  def faulted(a):
    a.nativeAcknowledged = False
    a.faultReason = 'critical'
  change(sm, 'aolAxisState', faulted)
  f.observe(sm, cp, cs, NOW + 20_000_000, latched=False, intent_producer_session=PRODUCER)
  assert f.failed


def test_latched_failure_is_still_fail_closed():
  cp, cs, f = baseline()
  fail_episode(cp, cs, f)
  # Without an unlatched idle frame the stale failure keeps the existing behavior.
  assert main_on_arm(cp, cs, f, NOW + 30_000_000, 4)

"""A lost host session is retired once, so a later engagement's token survives.

pandad reads AOL status (which evaluates the permission mask) before it sends
the engaged heartbeat for a new engagement. Before retirement, every status read
in that window re-cleared the token while the previous session flag stayed set,
so only the first engagement of a drive kept lateral through a brake.
"""

import pytest

from opendbc.safety.tests.test_ford_aol import TestFordAolDriverIntent as _FordNative

WORDS = (8, 10, 12, 18, 32, 66)
LONG_WORDS = (13, 33)
HOST_LAG = 10  # 100ms of status reads before pandad's next engaged heartbeat


@pytest.fixture
def ford_native():
  native = _FordNative(methodName='runTest')
  native.setUp()
  try:
    yield native
  finally:
    native.tearDown()


def select(native, word):
  native.reset(word)
  native.safety.set_aol_test_heartbeat(False)


def previous_session(n, *, main=4):
  """An earlier AOL session in this drive, then the host disengages with cruise MAIN off."""
  n.pump(40, main=0, heartbeat=False)
  n.pump(20, main=main, mask=1)
  assert n.safety.aol_get_permission_mask() & 1
  n.pump(40, main=0, heartbeat=False)
  assert n.safety.aol_get_permission_mask() == 0


def brake_to_standby(n):
  n.rx('EngBrakeData', {'BpedDrvAppl_D_Actl': 2, 'CcStat_D_Actl': 3})
  assert not n.safety.get_controls_allowed()


@pytest.mark.parametrize('word', WORDS)
@pytest.mark.parametrize('gas', (0., 25.))
def test_main_off_to_active_after_previous_session_retains_through_brake(ford_native, word, gas):
  # Logged Mach-E engagement: MAIN off -> ACC active in one frame, often with the accelerator held.
  n = ford_native
  select(n, word)
  previous_session(n)
  active = 5 if gas else 4
  n.pump(HOST_LAG, main=active, gas=gas, heartbeat=False)
  n.pump(20, main=active, gas=gas, mask=1)
  n.pump(20, main=4, mask=1)
  assert n.safety.get_controls_allowed()
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 1
  n.pump(30, main=3, brake=True, mask=1)
  n.pump(30, main=3, mask=1)
  assert n.safety.aol_get_permission_mask() == 1


@pytest.mark.parametrize('word', WORDS)
def test_standby_full_engagement_after_previous_session_retains_through_brake(ford_native, word):
  n = ford_native
  select(n, word)
  previous_session(n)
  n.pump(40, main=3, heartbeat=False)
  n.pump(HOST_LAG, main=4, heartbeat=False)
  n.pump(20, main=4, mask=1)
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 1


@pytest.mark.parametrize('word', WORDS)
def test_retired_session_token_still_expires_unclaimed(ford_native, word):
  n = ford_native
  select(n, word)
  previous_session(n)
  n.pump(40, main=4, heartbeat=False)  # > AOL_HOST_REQUEST_TIMEOUT_US without a host claim
  n.pump(10, main=4, mask=1)
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 0


@pytest.mark.parametrize('word', WORDS)
def test_host_loss_still_withdraws_claimed_token(ford_native, word):
  n = ford_native
  select(n, word)
  n.pump(40, main=0, heartbeat=False)
  n.pump(20, main=4, mask=1)
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 1
  n.pump(1, main=3, mask=1, heartbeat=False)
  assert n.safety.aol_get_permission_mask() == 0
  # The host returning does not revive the retired session without a new physical edge.
  n.pump(30, main=3, mask=1)
  assert n.safety.aol_get_permission_mask() == 0


@pytest.mark.parametrize('word', LONG_WORDS)
def test_long_profile_host_loss_still_withdraws_and_fresh_activation_engages(ford_native, word):
  n = ford_native
  safety = n.safety
  select(n, word)
  n.pump(40, main=0, heartbeat=False)
  n.pump(20, main=4, mask=3)
  assert safety.get_controls_allowed()
  n.pump(1, main=4, mask=3, heartbeat=False)
  assert not safety.get_controls_allowed()
  n.pump(20, main=4, heartbeat=False)
  assert not safety.get_controls_allowed()  # A stale activation cannot revive LONG.
  n.pump(20, main=3, heartbeat=False)
  n.pump(HOST_LAG, main=4, heartbeat=False)
  n.pump(20, main=4, mask=3)
  assert safety.get_controls_allowed()
  assert safety.aol_get_permission_mask() == 3


@pytest.mark.parametrize('word', WORDS)
def test_standby_activation_with_gas_held_arms_after_release(ford_native, word):
  # MADS-style: an ordinary activation from standby arms lateral even if the
  # driver engaged with the accelerator held, once the pedal is released.
  n = ford_native
  select(n, word)
  n.pump(40, main=3, heartbeat=False)  # MAIN already on: no MAIN edge token
  n.pump(10, main=3, gas=25., heartbeat=False)
  n.pump(HOST_LAG, main=5, gas=25., heartbeat=False)
  n.pump(20, main=5, gas=25., mask=1)
  assert n.safety.get_controls_allowed()
  n.pump(20, main=4, mask=1)
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 1
  n.pump(30, main=3, mask=1)
  assert n.safety.aol_get_permission_mask() == 1


@pytest.mark.parametrize('word', WORDS)
def test_activation_with_gas_held_until_disengaged_never_arms(ford_native, word):
  n = ford_native
  select(n, word)
  n.pump(40, main=3, heartbeat=False)
  n.pump(10, main=3, gas=25., heartbeat=False)
  n.pump(20, main=5, gas=25., mask=1)
  n.pump(10, main=3, gas=25., mask=1)  # paused before the pedal was released
  n.pump(20, main=3, mask=1)
  assert not n.safety.get_controls_allowed()
  assert n.safety.aol_get_permission_mask() == 0

"""A lost host session is retired once, so a later engagement's token survives.

pandad reads AOL status (which evaluates the permission mask) before it sends
the engaged heartbeat for a new engagement. Before retirement, every status read
in that window re-cleared the token while the previous session flag stayed set,
so only the first engagement of a drive kept lateral through a brake.
"""

import pytest

from opendbc.safety.tests.test_ford_full_engagement import WORDS, ford_native as ford_native, select

LONG_WORDS = tuple(word for word in WORDS if word & 1)
HOST_LAG = 10  # status-read ticks (100ms) between a physical edge and pandad's next engaged heartbeat


def cruise(n, state, *, brake=False):
  """One EngBrakeData frame, so a MAIN or cruise edge lands on a known tick."""
  n.rx('EngBrakeData', {'BpedDrvAppl_D_Actl': 2 if brake else 1, 'CcStat_D_Actl': state})


def engage_after_host_lag(n, state, *, gas=0.):
  """A physical edge, HOST_LAG status reads without a heartbeat, then the host engages and claims."""
  cruise(n, state)
  n.pump(HOST_LAG, main=state, gas=gas, heartbeat=False)
  n.pump(20, main=state, gas=gas, mask=1)


def previous_session(n):
  """An earlier AOL session in this drive, ended by MAIN off, then the host disengages."""
  n.pump(40, main=0, heartbeat=False)
  n.pump(20, main=4, mask=1)
  assert n.safety.aol_get_permission_mask() == 1
  n.pump(20, main=0, mask=1)
  assert n.safety.aol_get_permission_mask() == 0
  n.pump(40, main=0, heartbeat=False)


def brake_to_standby(n):
  cruise(n, 3, brake=True)
  assert not n.safety.get_controls_allowed()


@pytest.mark.parametrize('word', WORDS)
@pytest.mark.parametrize('gas', (0., 25.))
def test_main_off_to_active_after_previous_session_retains_through_brake(ford_native, word, gas):
  # Logged Mach-E engagement: MAIN off -> ACC active in one frame, often with the accelerator held.
  n = ford_native
  select(n, word)
  previous_session(n)
  n.pump(1, main=0, gas=gas, heartbeat=False)
  engage_after_host_lag(n, 5 if gas else 4, gas=gas)
  n.pump(20, main=4, mask=1)
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 1
  n.pump(30, main=3, brake=True, mask=1)
  n.pump(30, main=3, mask=1)
  assert n.safety.aol_get_permission_mask() == 1


@pytest.mark.parametrize('word', WORDS)
@pytest.mark.parametrize('gas', (0., 25.))
def test_standby_activation_after_previous_session_retains_through_brake(ford_native, word, gas):
  # The MAIN edge token expires unclaimed in standby, so the ordinary activation alone
  # arms lateral, with or without the accelerator held.
  n = ford_native
  select(n, word)
  previous_session(n)
  n.pump(50, main=3, gas=gas, heartbeat=False)
  engage_after_host_lag(n, 5 if gas else 4, gas=gas)
  n.pump(20, main=4, mask=1)
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 1


@pytest.mark.parametrize('word', WORDS)
def test_host_loss_on_the_edge_frame_keeps_the_next_token(ford_native, word):
  # The RX hook sees the lost heartbeat before any status read, on the frame of a new edge.
  n = ford_native
  select(n, word)
  n.pump(40, main=0, heartbeat=False)
  n.pump(20, main=4, mask=1)
  n.pump(20, main=0, mask=1)
  n.safety.set_aol_test_heartbeat(False)
  engage_after_host_lag(n, 4)
  brake_to_standby(n)
  assert n.safety.aol_get_permission_mask() == 1


@pytest.mark.parametrize('word', WORDS)
def test_retired_session_token_still_expires_unclaimed(ford_native, word):
  n = ford_native
  select(n, word)
  previous_session(n)
  cruise(n, 4)
  n.pump(35, main=4, heartbeat=False)  # 350ms > AOL_HOST_REQUEST_TIMEOUT_US without a host claim
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
  n.pump(20, main=4, mask=3)  # The host returns while the stale activation is still engaged.
  assert not safety.get_controls_allowed() and safety.aol_get_permission_mask() & 2 == 0
  n.pump(20, main=3, heartbeat=False)
  engage_after_host_lag(n, 4)
  n.pump(1, main=4, mask=3)
  assert safety.get_controls_allowed()
  assert safety.aol_get_permission_mask() == 3

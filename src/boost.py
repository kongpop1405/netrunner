"""Pick which boost the farm buys, without a config file per boost.

The buy chain has the same shape for every boost — probe the equipped pill, open
the shop, open the Multi picker, Multi-Buy, wait out the auto-roll, re-read the
pill — so only three things actually differ:

  banner    the equipped-boost pill the probe and the post-roll check read
  buy_taps  the taps that get from the shop to an open Multi picker
  multibuy  the picker's Multi-Buy button

`apply_boost` rewrites those in a loaded config. Which states to rewrite comes
from `boost_role` markers in the JSON rather than hardcoded state names: the
same profiles then work for any config that labels its chain, instead of only
the one whose states happen to be called buy_magnet and probe_magnet.

Coordinates are live-verified per profile. The three with banners were proven in
the configs they came from; the rest are listed with banner=None so `--boost`
can name them and explain exactly what is missing instead of failing obscurely.
"""
from __future__ import annotations

from .config import Config, ConfigError

#: Role -> what apply_boost does to states carrying it.
#:   probe   detect becomes the profile's banner (is the boost equipped?)
#:   buy     tap_xy actions are replaced, in order, by the profile's buy_taps
#:   picker  the first tap_xy becomes the profile's Multi-Buy button
#:   gate    on_match goto is redirected past the chain when boost is "none"
ROLES = ("probe", "buy", "picker", "gate")

#: "Pick desired Boosts!" rows, measured at 1920x1080: two columns at x=425 and
#: x=998, rows every ~74px from y=262. Tapping a row toggles its tick, and
#: Multi-Buy re-rolls until ANY ticked boost lands — so exactly one must be
#: ticked, and it must be the one we want.
PICK = {
    "doublecoins":   (425, 262),
    "score15":       (998, 262),
    "hpdrain15":     (425, 336),
    "revive80":      (998, 336),
    "crush70":       (425, 411),
    "speed":         (998, 411),
    "goldcoinmagic": (425, 485),
    "collision30":   (998, 485),
    "potions20":     (425, 559),
    "magnet":        (998, 559),
    "pitlifts2":     (425, 633),
}

PROFILES: dict[str, dict] = {
    "magnet": {
        "label": "Magnetic Aura",
        "banner": "boxrun/magneticaura_banner.png",
        "buy_taps": [(810, 875), (1645, 340)],
        "multibuy": (950, 880),
    },
    "speed": {
        "label": "+17% base speed",
        "banner": "boxrun/speedbase17_banner.png",
        # The shop opens on the HP-Upgrade view, where the pink Multi toggle
        # does not exist — (1649,337) lands on HP "Upgrade" there and the
        # Random Boost panel never opens, so the picker never appears and the
        # chain loops on retry_buy, re-rolling until the coins run out (seen
        # live 2026-08-02, 8 stacks burned). The Random Boost cell has to be
        # tapped first, exactly like magnet; the profile used to omit it.
        "buy_taps": [(810, 875), (1645, 340)],
        "multibuy": (953, 899),
    },
    "doublecoins": {
        "label": "Double Coins",
        "banner": "boxrun/doublecoins_banner.png",
        "buy_taps": [(755, 875), (1678, 305)],
        "multibuy": (953, 899),
    },
    # ── not usable yet: crop the pill at 1920x1080 and measure the buy taps ──
    # cookierun-classic-bot has all eleven cropped at 1280x720
    # (templates/BOOST_*.png). matchTemplate is single-scale, so those are a
    # reference for what the pill looks like, not files to drop in.
    "goldcoinmagic": {"label": "Gold Coin Magic", "banner": None},
    "crush70": {"label": "70% Crush Chance", "banner": None},
    "hpdrain15": {"label": "-15% HP Drain", "banner": None},
    "revive80": {"label": "Revive Once with 80 HP", "banner": None},
    "score15": {"label": "+15% Score Bonus", "banner": None},
    "potions20": {"label": "+20% HP from Potions", "banner": None},
    "collision30": {"label": "-30% Collision Damage", "banner": None},
    "pitlifts2": {"label": "2 Pit Lifts", "banner": None},
}

#: "none" is not a boost — it skips the buy chain entirely.
CHOICES = (*PROFILES, "none")


def ready() -> list[str]:
    """Boost keys whose profile is complete enough to run."""
    return [k for k, p in PROFILES.items() if p.get("banner")]


def describe_choices() -> str:
    """CLI help text: what can be picked now, and what each missing one needs."""
    lines = ["ready: " + ", ".join(ready()) + ", none"]
    pending = [f"{k} ({p['label']})" for k, p in PROFILES.items() if not p.get("banner")]
    if pending:
        lines.append("needs a banner crop @1920x1080 + buy-tap coords: "
                     + ", ".join(pending))
    return " | ".join(lines)


#: half-width of the roi drawn around a picker row's radio disc. Wide enough to
#: absorb the row's own anti-aliasing, tight enough that the neighbouring rows
#: (74px apart) can never fall inside it.
_PICK_ROI_PAD = 30

#: The radio disc in each state, cropped from a live picker. Matching one inside
#: a single row's roi is how a row's tick state is read.
UNTICKED_TEMPLATE = "giftdraw/pick_unticked.png"
TICKED_TEMPLATE = "giftdraw/pick_ticked.png"


def _roi(x: int, y: int) -> list[int]:
    return [x - _PICK_ROI_PAD, y - _PICK_ROI_PAD,
            _PICK_ROI_PAD * 2, _PICK_ROI_PAD * 2]


def _toggle_action(x: int, y: int, *, want_ticked: bool) -> dict:
    """Tap a picker row only when it is not already in the state we want.

    Each row is a toggle, so an unconditional tap flips a row that was already
    right. `optional` makes "template absent" mean "already in the wanted
    state, nothing to do" instead of an error.
    """
    return {
        "type": "tap_template",
        "template": UNTICKED_TEMPLATE if want_ticked else TICKED_TEMPLATE,
        "roi": _roi(x, y),
        "optional": True,
    }


def _roles(states: dict[str, dict]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {r: [] for r in ROLES}
    for name, st in states.items():
        role = st.get("boost_role")
        if role is None:
            continue
        if role not in found:
            raise ConfigError(
                f"state '{name}': unknown boost_role {role!r} (expected one of "
                f"{', '.join(ROLES)})")
        found[role].append(name)
    return found


def supports_boost(cfg: Config) -> bool:
    """True when the config labels a buy chain apply_boost can rewrite."""
    roles = _roles(cfg.states)
    return bool(roles["probe"] and roles["buy"] and roles["picker"])


def apply_boost(cfg: Config, choice: str) -> None:
    """Rewrite cfg.states in place so the buy chain targets `choice`.

    "none" routes the gate states past the chain, which is what running without
    a boost means. Any other choice needs a complete profile — an incomplete one
    would send taps at coordinates nobody has measured.
    """
    if choice not in CHOICES:
        raise ConfigError(f"unknown boost {choice!r} — {describe_choices()}")

    roles = _roles(cfg.states)

    if choice == "none":
        if not roles["gate"]:
            raise ConfigError(
                "boost 'none' needs at least one state marked "
                '"boost_role": "gate" to route past the buy chain')
        for name in roles["gate"]:
            target = cfg.states[name].get("boost_skip_goto")
            if not target:
                raise ConfigError(
                    f"state '{name}': boost_role 'gate' needs 'boost_skip_goto' "
                    f"naming the state to jump to when no boost is bought")
            for action in cfg.states[name].get("on_match", []):
                if action.get("type") == "goto":
                    action["state"] = target
        return

    profile = PROFILES[choice]
    if not profile.get("banner"):
        raise ConfigError(
            f"boost {choice!r} ({profile['label']}) has no banner template yet — "
            f"crop the equipped pill at 1920x1080 into templates/cookierun/ and "
            f"add its buy taps to PROFILES in src/boost.py")
    if not (roles["probe"] and roles["buy"] and roles["picker"]):
        missing = [r for r in ("probe", "buy", "picker") if not roles[r]]
        raise ConfigError(
            f"config has no boost chain to retarget (no state marked "
            f"\"boost_role\": {' / '.join(repr(m) for m in missing)})")

    for name in roles["probe"]:
        cfg.states[name]["detect"] = profile["banner"]

    taps = iter(profile["buy_taps"])
    for name in roles["buy"]:
        rebuilt: list[dict] = []
        drop_next_wait = False
        for action in cfg.states[name].get("on_match", []):
            if drop_next_wait and action.get("type") == "wait":
                # The wait only existed to let the dropped tap's screen settle.
                drop_next_wait = False
                continue
            drop_next_wait = False
            if action.get("type") == "tap_xy":
                nxt = next(taps, None)
                if nxt is None:
                    # This profile needs fewer taps than the baseline chain.
                    # No shipped profile does today — speed used to, on the
                    # claim that it reached Multi directly, which was wrong for
                    # a shop that opens on HP-Upgrade (see its buy_taps note).
                    drop_next_wait = True
                    continue
                action = {**action, "x": nxt[0], "y": nxt[1]}
            rebuilt.append(action)
        cfg.states[name]["on_match"] = rebuilt

    mb_x, mb_y = profile["multibuy"]
    pick_xy = PICK.get(choice)
    for name in roles["picker"]:
        actions = cfg.states[name].get("on_match", [])
        for action in actions:
            if action.get("type") == "tap_xy":
                action["x"], action["y"] = mb_x, mb_y
                break
        if pick_xy is not None:
            # Multi-Buy re-rolls until ANY ticked boost lands, so the picker has
            # to be left with exactly one tick — ours. Clear every other row
            # first (the game remembers ticks between visits), then set ours.
            prelude: list[dict] = []
            for key, xy in PICK.items():
                if key == choice:
                    continue
                prelude.append(_toggle_action(*xy, want_ticked=False))
            prelude.append(_toggle_action(*pick_xy, want_ticked=True))
            prelude.append({"type": "wait", "ms": [510, 720]})
            cfg.states[name]["on_match"] = prelude + actions
        else:
            cfg.states[name]["on_match"] = actions

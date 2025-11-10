import streamlit as st
import json
import pandas as pd
import matplotlib.pyplot as plt
import os
from openai import OpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, will use Streamlit secrets instead

# ------------------------------------------------------
# PAGE CONFIG
# ------------------------------------------------------
st.set_page_config(page_title="Congressional Politics Simulator", page_icon="🏛️", layout="wide")

# ------------------------------------------------------
# SIDEBAR SETUP
# ------------------------------------------------------
st.sidebar.header("🧭 Setup")

your_chamber = st.sidebar.selectbox(
    "Which chamber do you serve in?",
    ["House", "Senate"],
    key="chamber_select"
)
your_party = st.sidebar.selectbox(
    "Your party:",
    ["Democrat", "Republican"],
    key="party_select"
)
district_lean = st.sidebar.selectbox(
    "District/State Partisanship (Cook PVI):",
    ["D+10", "D+5", "EVEN", "R+5", "R+10"],
    index=2,  # Default to EVEN
    key="district_select"
)

st.sidebar.subheader("🧮 Party Breakdown")

if your_chamber == "House":
    chamber_D = st.sidebar.slider("House Democrats", 0, 435, 218, 1, key="chamber_d_slider")
    chamber_R = 435 - chamber_D
    st.sidebar.caption(f"House Republicans: **{chamber_R}** (Total = 435)")
    chamber_control = "Democrats" if chamber_D > chamber_R else "Republicans"
elif your_chamber == "Senate":
    chamber_D = st.sidebar.slider("Senate Democrats", 0, 100, 51, 1, key="chamber_d_slider")
    chamber_R = 100 - chamber_D
    st.sidebar.caption(f"Senate Republicans: **{chamber_R}** (Total = 100)")
    chamber_control = "Democrats" if chamber_D > chamber_R else "Republicans"

# ------------------------------------------------------
# MAIN HEADER
# ------------------------------------------------------
st.title("🏛️ Congressional Politics Simulator")
st.caption(
    "Balance your legislative ambitions with your political survival. "
    "Will you pass your bill **and** win reelection — or sacrifice your seat for policy success?"
)

# ------------------------------------------------------
# LOAD API KEY
# ------------------------------------------------------
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("⚠️ OpenAI API key not found. Please set `OPENAI_API_KEY` in environment variables or Streamlit Secrets.")
    st.stop()

# ------------------------------------------------------
# GAME EXPLAINER
# ------------------------------------------------------
with st.expander("📘 How to Play & Win"):
    st.markdown(
        """
### 🎮 Getting Started
Configure your member and political landscape in the sidebar.

### 🎯 Objective
Advance your bill through your chamber while keeping your reelection chances high.  
You have **8 turns** to navigate the process.

If your bill passes and you win reelection → **Full Victory**.  
If it passes but you lose → **Costly Victory**.  
If support collapses or time runs out → **Stalled Bill**.

### 🧠 Strategy
- Align moves with **district lean** and **chamber control**.  
- Risky actions boost progress but raise reelection risk.  
- Safe actions protect approval but slow progress.  
- **House:** Need 51% (218 votes).  
- **Senate:** Need 60% to overcome filibuster, unless reconciliation is used.  
        """
    )

# ------------------------------------------------------
# INITIAL STATE
# ------------------------------------------------------
if "turn" not in st.session_state:
    st.session_state.turn = 1
    st.session_state.support = None
    st.session_state.public = 50
    st.session_state.chamber_progress = 0
    st.session_state.reelection_risk = 0
    st.session_state.history = []
    st.session_state.trends = pd.DataFrame(
        columns=["Turn", "Support", "Public", "ReelectionRisk", "ReelectionChance", "ChamberProgress"]
    )
    st.session_state.game_over = False
    st.session_state.input_counter = 0

# ------------------------------------------------------
# GPT SIMULATION ENGINE
# ------------------------------------------------------
def gpt_simulate(action_text):
    client = OpenAI(api_key=api_key)

    system_prompt = (
    "You are a political simulation engine for the U.S. Congress.\n"
    "Return a ≤120-word narrative, then a JSON object with numeric deltas.\n\n"

    "INPUT DEFINITIONS\n"
    "- Chamber support = % of legislators likely to vote yes.\n"
    "- Chamber progress = procedural momentum (committee → floor → passage).\n"
    "- Public approval = district opinion (affects reelection only).\n\n"

    "**CHAMBER PROCEDURAL REALISM**\n"
    "- The House operates by simple majority (51%).\n"
    "- The Senate normally requires 60 votes for cloture.\n"
    "- Under reconciliation, the Senate needs only 51 votes and bypasses cloture.\n"
    "- Do **not** mention reconciliation or cloture unless the user mentions them.\n\n"

    "**POLITICAL ISSUE CONTEXT**\n"
    "Some issues are elite-partisan but mass-mixed (e.g., abortion, marijuana legalization, same-sex marriage). "
    "Treat these as wedge issues: they should have highly polarized chamber reactions but relatively stable or mildly positive public reactions.\n\n"

    "**HARD RULES**\n"
    "1) Separate worlds: District/public approval NEVER affects chamber progress.\n"
    "2) Chamber support ceilings must follow composition realism:\n"
    "   - Let majority_share = (majority_party_seats / total_seats) × 100.\n"
    "   - **For partisan or controversial bills:** max_support = majority_share + 5.\n"
    "   - **For bipartisan or consensus bills:** max_support = majority_share + 10 (never above 80).\n"
    "   - Minority-party bills start ≈35–45% and cannot exceed 50 without bipartisan cooperation or reconciliation.\n"
    "3) Chamber progress depends ONLY on support level and leadership/procedure. Once support > threshold, progress cannot decrease unless there is a procedural defeat.\n\n"

    "**SUPPORT INCREMENT RULES (Hard Enforcement)**\n"
    "- support_change values must *always* be nonzero unless the bill is defeated or withdrawn.\n"
    "- Use these fixed numeric ranges depending on context:\n"
    "  - When chamber support < threshold (House <51% / Senate <60%):\n"
    "      + Outreach / lobbying / coalition-building: +2–5\n"
    "      + Procedural or symbolic actions: +2–4\n"
    "  - When chamber support ≥ threshold but <70%: +0–2 (stabilization or consolidation)\n"
    "  - When major leadership / committee / media events occur: +2–5 (never zero)\n"
    "  - Never output zero for support_change unless support >70% (already overwhelming) or the action clearly fails.\n"
    "- Irrelevant actions or inaction should yield zero or negative support changes.\n"
    "- Chamber support cannot exceed majority_share +5 (partisan) or +10 (bipartisan).\n"
    "- Apply these numeric ranges *strictly*, regardless of narrative tone.\n\n"

    "**NUMERIC RULES — HARD-CODED AND MANDATORY**\n"
    "- Treat all thresholds as fixed constants: House = 51%, Senate = 60%.\n"
    "- For the House: decisive = 55%, overwhelming = 70%.\n"
    "- For the Senate: decisive = 65%, overwhelming = 75%.\n"
    "- These zones are non-negotiable.\n\n"

    "**PROGRESS ZONES (MANDATORY OUTPUT RANGES)**\n"
    "- Below threshold (<51% House / <60% Senate): chamber_progress_change = +10–20.\n"
    "- Momentum zone (51–55% House / 60–65% Senate): chamber_progress_change = +25–30.\n"
    "- Decisive zone (>55% House / >65% Senate): chamber_progress_change = +30–40.\n"
    "- Overwhelming (≥70% House / ≥75% Senate): chamber_progress_change = +35–45.\n"
    "- Minority-party bills: +5–10 only, capped at ~50 progress unless bipartisan or reconciliation is used.\n\n"

    "**PROCEDURAL MODIFIERS (RECONCILIATION LOGIC)**\n"
    "- If the chamber is the Senate and reconciliation is in discussion (`reconciliation_discussed == True`), "
    "treat the 60% cloture requirement as waived and apply progress as if the threshold were 51%.\n"
    "- When reconciliation is not in discussion and the user's party is in the minority, "
    "cap `chamber_progress_change` at +5 and `support_change` at +2 to reflect gridlock.\n"
    "- Once reconciliation is being pursued, allow larger progress changes (+15–25) even without 60% support, "
    "representing fast-tracking.\n"
    "- Never let progress exceed 100% or fall below +5 when support ≥ threshold.\n\n"

    "**REELECTION THRESHOLD LOGIC**\n"
    "- Public approval >55%: reelection odds improve noticeably.\n"
    "- 45–55%: reelection uncertain; risk changes small.\n"
    "- <45%: reelection risk rises sharply.\n"
    "- In evenly divided or opposing districts, controversial actions create proportional backlash.\n\n"

    "**MAGNITUDES**\n"
    "- support_change: ±2–8 (smaller for partisan bills)\n"
    "- public_change: D-lean + Dem policy or R-lean + GOP policy = +5–10; misaligned −5–10; EVEN = −2..+2 on divisive issues\n"
    "- reelection_risk: +0–8 (independent of public_change; avoid double-counting)\n\n"

    "**OUTPUT FORMAT**\n"
    "Write a short narrative (≤150 words) describing this turn’s outcome.\n"
    "Then output ONLY a JSON object like:\n"
    "{\n"
    "  \"support_change\": int,\n"
    "  \"public_change\": int,\n"
    "  \"chamber_progress_change\": int,\n"
    "  \"reelection_risk\": int\n"
    "}\n\n"

    "**INSTRUCTIONS FOR THIS TURN**\n"
    "- Use the chamber composition, party control, and district lean provided in the user input.\n"
    "- Apply ceilings, numeric progress rules, and reelection logic using live inputs.\n"
    "- Choose progress increment strictly from the correct support zone.\n"
    "- Incorporate procedural context such as reconciliation discussion when determining progress.\n"
    "- Reference live support, public, and progress values.\n"
    "- When narrative context conflicts with numeric rules, numeric realism takes priority.\n"
    )


    # --- Determine current (pre-turn) stats ---
    if st.session_state.support is None or st.session_state.turn == 1:
        if your_chamber == "House":
            chamber_baseline = (chamber_D / (chamber_D + chamber_R) * 100) - 15
        else:
            chamber_baseline = (chamber_D / (chamber_D + chamber_R) * 100) - 15
        current_support = round(chamber_baseline)
    else:
        current_support = st.session_state.support

    # Optional: context phrasing
    context_note = (
        "At the start of the session, before any lobbying or media efforts,"
        if st.session_state.turn == 1
        else "Following previous actions,"
    )

    try:
        # --- Single GPT call: compute + narrate after applying changes ---
        user_prompt = f"""
{context_note}

Member info:
- Chamber: {your_chamber}
- Party: {your_party}
- District Lean: {district_lean}
- Composition: {chamber_D} D / {chamber_R} R (Control: {chamber_control})

Current stats (before this turn):
- Support: {current_support}% ({'below' if current_support < 51 else 'above'} majority threshold)
- Public Approval: {st.session_state.public}%
- Chamber Progress: {st.session_state.chamber_progress}%
- Reelection Risk: {st.session_state.reelection_risk}

Action this turn: {action_text}

Steps:
1. Decide reasonable numeric deltas for this action and output them in JSON
   {{ "support_change": int, "public_change": int,
      "chamber_progress_change": int, "reelection_risk": int }}
2. Then, **using those deltas**, narrate the *after-change* outcome in ≤120 words.
   Show the updated numbers (e.g., "support rose to X%, progress reached Y%").
3. Do not repeat the JSON verbatim in the narrative.
4. Follow realism rules:
   - Early turns → modest deltas (support ±3–5, progress ≤15)
   - Maintain neutrality for even districts unless provoked
   - Never let progress exceed 100%

Output format:
<NARRATIVE>
{{
  "support_change": int,
  "public_change": int,
  "chamber_progress_change": int,
  "reelection_risk": int
}}
"""

        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = r.choices[0].message.content

        # --- Parse JSON at the end ---
        try:
            json_part = text[text.index("{"): text.rindex("}") + 1]
            data = json.loads(json_part)
        except Exception:
            data = dict(support_change=0, public_change=0,
                        chamber_progress_change=0, reelection_risk=0)

        # --- Apply deltas after parsing ---
        st.session_state.support = (st.session_state.support or current_support) + data["support_change"]
        st.session_state.public += data["public_change"]
        st.session_state.chamber_progress += data["chamber_progress_change"]
        st.session_state.reelection_risk += data["reelection_risk"]

        return text, data

    except Exception as e:
        return f"⚠️ GPT error: {e}", dict(support_change=0, public_change=0,
                                          chamber_progress_change=0, reelection_risk=0)



# ------------------------------------------------------
# HELPERS
# ------------------------------------------------------
def calc_reelection_chance():
    base = 50
    if (your_party == "Democrat" and "D+" in district_lean) or (your_party == "Republican" and "R+" in district_lean):
        base += 15
    elif "EVEN" in district_lean:
        base += 5
    else:
        base -= 10
    chance = base + (st.session_state.public - 50) - st.session_state.reelection_risk
    return max(0, min(100, chance))

def update_trends(chance):
    st.session_state.trends = pd.concat(
        [
            st.session_state.trends,
            pd.DataFrame(
                [dict(
                    Turn=st.session_state.turn,
                    Support=st.session_state.support,
                    Public=st.session_state.public,
                    ReelectionRisk=st.session_state.reelection_risk,
                    ReelectionChance=chance,
                    ChamberProgress=st.session_state.chamber_progress,
                )]
            ),
        ],
        ignore_index=True,
    )

def plot_trends(df):
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(df["Turn"], df["Support"], label="Support", marker='o')
    ax.plot(df["Turn"], df["Public"], label="Public Approval", marker='s')
    ax.plot(df["Turn"], df["ReelectionChance"], label="Reelection Chance", marker='^')
    ax.plot(df["Turn"], df["ChamberProgress"], label="Chamber Progress", marker='d')
    ax.set_xlabel("Turn")
    ax.set_ylabel("Score (%)")
    ax.legend(loc='best', fontsize=8)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_ylim(0, 105)
    st.pyplot(fig)

# ------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------
if not st.session_state.game_over:
    if st.session_state.turn > 8:
        st.session_state.game_over = True
        st.error("❌ Stalled Bill — Your legislation failed to advance before the session ended.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"Turn {st.session_state.turn} of 8")
            support_display = 0 if st.session_state.support is None else round(st.session_state.support)
            st.write(f"**Support in Chamber:** {support_display}% | **Public Support in District:** {round(st.session_state.public)}%")
            if st.session_state.support is None:
                st.caption("First-turn actions establish your initial coalition strength.")
        with c2:
            reelection_chance = calc_reelection_chance()
            st.metric("🗳️ Projected Reelection Chance", f"{reelection_chance:.0f}%")

        st.markdown(f"### Bill Progress in {your_chamber}")
        chamber_icon = "🏠" if your_chamber == "House" else "🏛"
        threshold_text = "Need 51% support for final passage" if your_chamber == "House" else "Need 60% support to overcome filibuster"
        st.write(f"{chamber_icon} **{your_chamber}:** {st.session_state.chamber_progress}% complete")
        st.caption(threshold_text)
        st.progress(st.session_state.chamber_progress / 100)

        st.divider()
        st.write("💬 Enter your action for this turn (e.g., *'Negotiate with leadership'*, *'Hold town hall'*, *'Push through committee'*):")

        action = st.text_input(
            "Your action:",
            key=f"action_input_{st.session_state.input_counter}",
            placeholder="Type your action..."
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            submit = st.button("🚀 Submit Action", use_container_width=True, key="submit_btn")
        with col2:
            clear = st.button("🧹 Clear Box", use_container_width=True, key="clear_btn")

        if clear:
            st.session_state.input_counter += 1
            st.rerun()

        if submit:
            if action:
                narrative, data = gpt_simulate(action)

                if st.session_state.support is None:
                    majority_share = round((chamber_D / (chamber_D + chamber_R)) * 100)
                    st.session_state.support = max(0, min(100, majority_share - 15 + data["support_change"]))
                    st.session_state.public = max(0, min(100, 50 + data["public_change"]))
                else:
                    st.session_state.support = max(0, min(100, st.session_state.support + data["support_change"]))
                    st.session_state.public = max(0, min(100, st.session_state.public + data["public_change"]))

                st.session_state.chamber_progress = max(0, min(100, st.session_state.chamber_progress + data["chamber_progress_change"]))
                st.session_state.reelection_risk += max(0, data["reelection_risk"])

                reelection_chance = calc_reelection_chance()
                update_trends(reelection_chance)
                st.session_state.history.append((action, narrative))
                st.session_state.turn += 1

                if st.session_state.chamber_progress >= 100:
                    if reelection_chance >= 50:
                        st.session_state.game_over = True
                        st.success(f"🏆 Full Victory — Your bill passed the {your_chamber} and you won reelection!")
                    else:
                        st.session_state.game_over = True
                        st.warning(f"😬 Costly Victory — Your bill passed the {your_chamber} but you lost reelection.")
                elif st.session_state.support is not None and st.session_state.support < 20:
                    st.session_state.game_over = True
                    st.error("❌ Stalled Bill — Your legislation lost critical support and failed.")

                st.write(narrative)
                plot_trends(st.session_state.trends)
                st.session_state.input_counter += 1
            else:
                st.warning("⚠️ Please enter an action first!")

else:
    st.header("📊 Final Results")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Support", f"{round(st.session_state.support)}%")
    with col2: st.metric("Public Approval", f"{round(st.session_state.public)}%")
    with col3: st.metric("Chamber Progress", f"{round(st.session_state.chamber_progress)}%")

    final_chance = calc_reelection_chance()
    st.metric("🗳️ Final Reelection Chance", f"{final_chance:.0f}%")
    st.subheader("📈 Performance Over Time")
    plot_trends(st.session_state.trends)

    if final_chance > 70:
        st.success("You were reelected comfortably — your district rewards your leadership!")
    elif final_chance > 40:
        st.warning("You narrowly survived reelection — your bold votes polarized voters.")
    else:
        st.error("You lost your seat. History may yet remember your efforts kindly.")

    if st.button("🔁 Play Again", key="play_again_btn"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

with st.expander("📜 Game Log"):
    for i, (a, n) in enumerate(st.session_state.history, start=1):
        st.markdown(f"**Turn {i}:** {a}\n\n{n}")

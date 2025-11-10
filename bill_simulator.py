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

    system_prompt = """
    You are the institutional logic engine of a U.S. congressional simulation.
    Model all behavior as if operating within the real constraints of Congress.

    INSTITUTIONAL FOUNDATIONS
    - The U.S. House is a majoritarian chamber: floor control by the majority party.
      - Passage threshold = 51% support.
      - Rules Committee and leadership can use closed rules to protect members and restrict amendments.
    - The U.S. Senate is a supermajoritarian chamber: floor action governed by cloture and filibuster.
      - Standard cloture threshold = 60% support to end debate.
      - Simple-majority passage possible only if the filibuster is overcome (via cloture) or bypassed through reconciliation.
    - Reconciliation (budget-related path):
      - Allows the majority party to pass with a simple majority (51%).
      - Limited debate, narrow scope; cannot be used for all policy areas.
    - Minority-party or bipartisan dynamics must reflect chamber structure:
      - House: majority dominance, limited cross-party influence.
      - Senate: cross-party bargaining essential unless reconciliation is invoked.

    OUTPUT STRUCTURE
    - Each turn, write a concise narrative (2–4 sentences) explaining developments in this institutional context.
    - Then output JSON with four numeric deltas:
      {
        "support_change": X,
        "public_change": Y,
        "chamber_progress_change": Z,
        "reelection_risk": R
      }

    Interpret and enforce all numeric and procedural rules from the user prompt faithfully.
    """

    # ------------------------------------------------------------
    # PRE-PROMPT STATE SETUP  (must run before building user_prompt)
    # ------------------------------------------------------------

    # --- Compute baseline once at game start ---
    if "support" not in st.session_state or st.session_state.support is None:
        chamber_total = (chamber_D or 0) + (chamber_R or 0)
        if chamber_total == 0:
            chamber_total = 1  # defensive guard

        # Compute share of seats for player's party
        party_share = (
            (chamber_D / chamber_total) * 100
            if your_party == "Democrat"
            else (chamber_R / chamber_total) * 100
        )

        # Apply fixed baseline offset (e.g., -12 for realism)
        chamber_baseline = party_share - 12

        # Keep the baseline within reasonable bounds (20–60%)
        chamber_baseline = max(20, min(chamber_baseline, 60))

        # Store baseline support in session state
        st.session_state.support = round(chamber_baseline)

    # --- Retrieve persistent state for this turn ---
    current_support = st.session_state.support or 0

    # --- Detect reconciliation (once mentioned, stays True) ---
    if "reconciliation_discussed" not in st.session_state:
        st.session_state.reconciliation_discussed = False

    if "reconciliation" in action_text.lower():
        st.session_state.reconciliation_discussed = True

    # --- Narrative phrasing for Turn 1 vs later turns ---
    if "turn" not in st.session_state:
        st.session_state.turn = 1  # defensive default

    context_note = (
        "At the start of the session, before any lobbying or media efforts,"
        if st.session_state.turn == 1
        else "Following previous actions,"
    )

    # --- Optional: dynamic reconciliation note for prompt ---
    recon_note = (
        "Reconciliation is currently being discussed; treat the Senate threshold as 51%."
        if st.session_state.reconciliation_discussed and your_chamber == "Senate"
        else ""
    )


    try:
        # --- Single GPT call: compute + narrate after applying changes ---
        user_prompt = f"""
        {context_note}

        Member Info
        - Chamber: {your_chamber}
        - Party: {your_party}
        - District Lean: {district_lean}
        - Composition: {chamber_D} D / {chamber_R} R (Control: {chamber_control})

        Current Stats (before this turn)
        - Support: {current_support}% of the entire {your_chamber} (not just your party caucus)
          ({'below' if current_support < 51 else 'above'} the majority threshold)
        - Public Approval: {st.session_state.public}%
        - Chamber Progress: {st.session_state.chamber_progress}%
        - Reelection Risk: {st.session_state.reelection_risk}
        
        - For calculations: new_support = current_support + support_change
          (Use this value when applying the progress-zone rules.)
        - Reminder: If new_support ≥ threshold, you must apply the “above-threshold” range (25–35).


        Action This Turn
        {action_text}

        ------------------------------------------------------------
        NUMERIC RULES — SUPPORT, PROGRESS & REELECTION
        ------------------------------------------------------------
        1. **Thresholds for passage**
           - House: 51%
           - Senate: 60%
           - If reconciliation is being used in the Senate, use 51% instead of 60%.
           - Once reconciliation is invoked or actively discussed as a truly viable path 
             (i.e., the proposal qualifies under the Byrd Rule and is confirmed as eligible),
             apply this reduced threshold for all subsequent turns. 
             Make sure to clearly acknowledge reconciliation in the narrative 
             (e.g., “using the reconciliation process to bypass the filibuster”).
             Do not continue to refer to a 60% threshold once reconciliation is in effect.
             Use the chamber progress pacing rules defined below, where the threshold 
             is now 51, to determine appropriate progress increases under reconciliation.

        2. **Support calculation**
           - First, calculate the *new support level*:
             new_support = current_support + support_change
           - This new_support value determines which progress zone applies.

        3. **Progress zones (MANDATORY)**
           Always base the progress zone on the *new_support* value 
           (i.e., current_support + support_change), not the previous turn’s support.
           Determine chamber_progress_change based on current support level and the nature of the action:

           • **Below threshold** (House <51% / Senate <60%):
             - chamber_progress_change = 10–25 only for actions that plausibly build support.

           • **At or above threshold**:
             - chamber_progress_change = 25–35 for politically significant or procedural actions 
               (e.g., committee markup, leadership negotiation, floor scheduling, final vote).
             - chamber_progress_change = 20–25 for neutral, symbolic, or maintenance actions 
               (e.g., “do nothing,” “minor statement,” “routine press release,” or 
               member-maintenance and coalition-building efforts). When support has been rising 
               steadily across several turns, favor the **upper half** of this range (23–25).
             - chamber_progress_change = 0–20 for reckless, controversial, or backfiring actions.

           - Values outside the ranges given above are **not permitted**.

           - **Late-stage acceleration (MANDATORY)**:
             If total chamber_progress is 75% or higher **and** the player’s action is procedural,
             leadership-oriented, or directly related to scheduling or passage 
             (e.g., rule adoption, final negotiations, floor vote), 
             then chamber_progress_change **must** be within 25–35.

           - Do **not** slow or reduce the chosen change merely because total progress 
             is near or above 100%. Let chamber_progress exceed 100% if needed to 
             reflect decisive passage or overwhelming momentum. 
             Treat any value at or above 100% as a completed bill for narrative purposes.
           - In this late stage, you must still select a value within 25–35 
             unless the action clearly backfires. Do not deliberately choose 
             smaller numbers just because progress is already near 100 %.

           - **Momentum scaling (MANDATORY)**:
             If support has increased for three or more consecutive turns, 
             raise the lower and upper bounds of any applicable progress range by +5. 
             This ensures momentum translates into visible acceleration.


        4. **Scaling within the range**
           - Choose the exact chamber_progress_change based on:
             (a) The *magnitude* of support_change this turn.
             (b) The *strategic significance* of the action (e.g., leadership meeting, procedural step).
             (c) The *likelihood that this action materially increases the bill’s chance of passage.*

        5. **Support-change guidelines**
           - Typical values: ±2–6 depending on action type and timing.
           - Early turns or symbolic actions → smaller (±2–4).
           - Direct negotiation, leadership, or procedural breakthroughs → larger (+4–6).
           - Negative values (−1 to −4) occur only if the action backfires, causes controversy,
             or alienates moderates.
           - Never output 0 unless the action is explicitly ineffective or purely administrative.

           - Support should represent backing across the entire chamber, not just your own party.
             It should rarely exceed the member’s party seat share **plus about 3 percentage points**
             unless a clear bipartisan breakthrough occurs. 
             Once support approaches this ceiling, choose smaller positive changes (+1–2) 
             or stabilization (0) rather than continued large increases.


        6. **Public support and reelection risk relationship (MANDATORY)**
           - Reelection risk changes should mirror changes in public support, just as chamber progress mirrors chamber support.
           - First, calculate the *new public approval*:
             new_public = current_public + public_change
           - Then determine reelection risk based on that new value.

           - If new_public is **above 55%**, risk should be **low (0–2)**.
           - If new_public is **between 45% and 55%**, risk should be **moderate (3–5)**.
           - If new_public is **below 45%**, risk should be **high (6–8)**.

           - When public_change is positive, reduce reelection_risk proportionally (typically −1 to −3).
           - When public_change is negative, increase reelection_risk proportionally (+1 to +3).
           - The final reelection_risk value must remain between **0 and 10**.

           - District lean may slightly modify these outcomes:
             • If district lean aligns with the member’s policy, risk may drop by 1.
             • If district lean opposes it, risk may increase by 1.
           - **Do not assign a value of 10** unless public approval falls below **40%**
             or the action clearly triggers severe backlash or scandal.

        ------------------------------------------------------------
        INSTRUCTIONS
        ------------------------------------------------------------
        1. Decide reasonable numeric deltas for this action and output them in JSON. 
           Remember to use new_support when deciding chamber_progress_change,
           and ensure the chosen chamber_progress_change stays strictly within the mandated range for its zone.
           Reelection risk should be recalculated fresh each turn based on the new public approval 
           and district lean, not accumulated from prior values. A small change in public approval 
           (±1–2 points) should cause only a correspondingly small change in risk (±1–2 points).

           {{
             "support_change": int,
             "public_change": int,
             "chamber_progress_change": int,
             "reelection_risk": int
           }}

        2. Then, **using those deltas**, narrate the *after-change* outcome in ≤120 words.
           Include the updated numbers (e.g., "support rose to X%, progress reached Y%").

        3. Do not repeat the JSON verbatim in the narrative.

        4. Follow realism rules:
           - Early turns → modest deltas (support ±3–5, progress ≤15)
           - Maintain neutrality for even districts unless provoked
           - Never let total chamber progress exceed 100%
           - Do not artificially slow progress when nearing 100%. Let chamber progress reach 100% naturally.
           - If chamber_progress appears low relative to repeated increases in support,
            adjust upward within the allowed range so that momentum is visible to the player.

        Output Format
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

                # Calculate player's party share and dynamic realism cap
                if your_party == "Democrat":
                    party_share = (chamber_D / (chamber_D + chamber_R)) * 100
                else:
                    party_share = (chamber_R / (chamber_D + chamber_R)) * 100
                support_cap = min(100, party_share + 5)

                if st.session_state.support is None:
                    # First-turn baseline (majority_share - 15 realism offset)
                    majority_share = round((chamber_D / (chamber_D + chamber_R)) * 100)
                    st.session_state.support = max(
                        0,
                        min(support_cap, majority_share - 15 + data["support_change"])
                    )
                    st.session_state.public = max(
                        0, min(100, 50 + data["public_change"])
                    )
                else:
                    st.session_state.support = max(
                        0,
                        min(support_cap, st.session_state.support + data["support_change"])
                    )
                    st.session_state.public = max(
                        0,
                        min(100, st.session_state.public + data["public_change"])
                    )

                st.session_state.chamber_progress = max(0, min(100, st.session_state.chamber_progress + data["chamber_progress_change"]))
                st.session_state.reelection_risk = max(0, min(10, data["reelection_risk"]))

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

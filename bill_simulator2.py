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
    key="district_select"
)

st.sidebar.subheader("🧮 Party Breakdown")

# Only show party breakdown for selected chamber
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
**Before playing, make your selections in the sidebar (←) to configure your member and set the political landscape.**

        
        ### 🎯 Objective
Advance your bill through your chamber while keeping your reelection chances high.  
You have **8 turns** to navigate the process.

If your bill passes your chamber and you win reelection → **Full Victory**.  
If it passes but you lose reelection → **Costly Victory**.  
If you fail to advance before 8 turns or support drops too low → **Stalled Bill**.

| Rank | Outcome | Description |
|------|----------|-------------|
| 1️⃣ | 🏆 **Full Victory** | Passed your chamber + won reelection. |
| 2️⃣ | 😬 **Costly Victory** | Passed your chamber but lost reelection. |
| 3️⃣ | ❌ **Stalled Bill** | Failed to advance before 8 turns or support < 20%. |

### 🧠 Strategy Tips
- Align moves with your **district lean** and **chamber control**.  
- Risky actions speed up progress but raise reelection risk.  
- Consensus actions protect approval but may slow advancement.  
- **House vs Senate matters:**
  - **House**: Need 51% support (218 votes) for final passage. Majority party has strong procedural control.
  - **Senate**: Need 60% support (60 votes) to overcome filibuster, unless using reconciliation (51 votes). Individual senators have more power.
- Track:  
  - 🏛 **Support in Chamber** = share of legislators backing your bill.  
  - 📊 **Public Support in District** = voter sentiment in your district.  
  - 🗳 **Reelection Chance** = calculated each turn.  
  - 📈 **Chamber Progress** = procedural advancement toward passage (0-100%).
        """
    )

# ------------------------------------------------------
# INITIAL STATE
# ------------------------------------------------------
if "turn" not in st.session_state:
    st.session_state.turn = 1
    st.session_state.support = None   # GPT sets after Turn 1
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

    # Determine support threshold based on chamber
    if your_chamber == "House":
        threshold_text = "In the House, the majority party has strong procedural control. Progress moves faster with party unity. The member needs 51% support (218 votes) to pass final votes. Progress cannot exceed 85% unless support is above 51%."
    else:  # Senate
        threshold_text = "In the Senate, 60 votes are typically needed to invoke cloture and overcome a filibuster. Progress is slower and requires bipartisan support OR use of reconciliation (which only needs 51 votes). Progress cannot exceed 85% unless support is above 60% (or 51% if explicitly using reconciliation). When reaching 100% progress, describe both cloture and final passage votes in your narrative."
    system_prompt = (
        "You are a political simulation engine for the U.S. Congress.\n"
        "Return a ≤120-word narrative, then a JSON object with numeric deltas.\n"
        "\n"
        "INPUT DEFINITIONS\n"
        "- Chamber support = % of legislators likely to vote yes.\n"
        "- Chamber progress = procedural momentum (committee→floor→passage).\n"
        "- Public approval = district opinion (affects reelection only).\n"
        "\n"
        "HARD RULES\n"
        "1) Separate worlds: District/public approval NEVER affects chamber progress.\n"
        "2) Chamber support ceilings must follow composition realism:\n"
        "   - Let majority_share = (majority_party_seats / total_seats) × 100.\n"
        "   - **For partisan/controversial bills:** max_support = majority_share + 5.\n"
        "   - **For bipartisan/consensus bills:** max_support = majority_share + 10 (never above 80).\n"
        "   - Minority-party bills start ≈35–45 % and cannot exceed 50 without bipartisan cooperation.\n"
        "   - If computed support exceeds max_support, cap it and note 'cap_applied=true'.\n"
        "3) Chamber progress depends ONLY on support level + leadership/procedure. Once support > threshold, progress cannot decrease unless there is a procedural defeat.\n"
        "4) Progress thresholds (House / Senate): Passage 51 / 60; decisive 55 / 65; overwhelming 70 / 75.\n"
        "\n"
        "PROGRESS INCREMENTS (by support zone)\n"
        "- Below threshold: +5–15\n"
        "- Momentum zone (House 51–55 / Senate 60–65): +20–25\n"
        "- Decisive zone (House>55 / Senate>65): ≥+25, typically +30–35\n"
        "- Overwhelming (House≥70 / Senate≥75): +30–35\n"
        "Always increase progress once above threshold until 100 unless a defeat occurs.\n"
        "\n"
        "MAGNITUDES\n"
        "- support_change: ±3–15\n"
        "- public_change: D-lean + Dem policy or R-lean + GOP policy = +5–10; misaligned −5–10; EVEN = −2..+2 on divisive issues\n"
        "- reelection_risk: +0–8 (independent of public_change; avoid double-counting)\n"
        "\n"
        "OUTPUT FORMAT\n"
        "Write the ≤120-word narrative first. Then output JSON:\n"
        "{\n"
        "  \"support_change\": int,\n"
        "  \"public_change\": int,\n"
        "  \"chamber_progress_change\": int,\n"
        "  \"reelection_risk\": int\n"
        "}\n"
        "\n"
        "# DEBUG (calc block)\n"
        "# The following hidden structure can be activated for tuning realism.\n"
        "# To re-enable, append this inside the JSON after reelection_risk:\n"
        "#   , \"calc\": {\"majority_share_pct\": int, \"support_zone\": str, \"cap_applied\": bool, \"bipartisan\": bool, \"reconciliation\": bool}\n"
        "# Leave it disabled for normal gameplay; keep code intact so it can be reactivated later.\n"
        "\n"
        "INSTRUCTIONS FOR THIS TURN\n"
        "- Use the chamber composition, party control, and district lean provided in the user input.\n"
        "- Apply all ceilings and progress rules using the current support and chamber percentages.\n"
        "- Choose progress increment strictly from the correct support zone (below, momentum, decisive, overwhelming).\n"
        "- Reference the live support, public, and progress values from the input when producing new deltas.\n"
        "- When narrative context conflicts with numeric rules, the numeric realism rules take priority.\n"
    )


    user_prompt = f"""
Member info:
- Chamber: {your_chamber}
- Party: {your_party}
- District Lean: {district_lean}

Chamber Composition:
- {your_chamber}: {chamber_D} D / {chamber_R} R (Control: {chamber_control})

Current stats:
- Support: {st.session_state.support}
- Public Approval: {st.session_state.public}
- Chamber Progress: {st.session_state.chamber_progress}
- Reelection Risk: {st.session_state.reelection_risk}

Action this turn: {action_text}

Respond with a short paragraph (≤150 words) describing what happens,  
then output a JSON object like:
{{"support_change": int, "public_change": int, "chamber_progress_change": int, "reelection_risk": int}}
"""

    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
        )
        text = r.choices[0].message.content
        try:
            json_part = text[text.index("{"): text.rindex("}") + 1]
            data = json.loads(json_part)
        except Exception:
            data = dict(
                support_change=0, public_change=0,
                chamber_progress_change=0,
                reelection_risk=0
            )
        return text, data
    except Exception as e:
        return f"⚠️ GPT error: {e}", dict(
            support_change=0, public_change=0,
            chamber_progress_change=0,
            reelection_risk=0
        )

# ------------------------------------------------------
# HELPERS
# ------------------------------------------------------
def calc_reelection_chance():
    base = 50
    if (your_party == "Democrat" and "D+" in district_lean) or (
        your_party == "Republican" and "R+" in district_lean
    ):
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
    # Check turn limit FIRST
    if st.session_state.turn > 8:
        st.session_state.game_over = True
        st.error("❌ Stalled Bill — Your legislation failed to advance before the session ended.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"Turn {st.session_state.turn} of 8")
            support_display = st.session_state.support if st.session_state.support is not None else 0
            st.write(f"**Support in Chamber:** {support_display}% | **Public Support in District:** {st.session_state.public}%")
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
        st.write("💬 Enter your action for this turn "
                 "(e.g., *'Negotiate with leadership'*, *'Hold town hall'*, *'Push through committee'*):")

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

                # ---- First-turn baseline set by GPT ----
                if st.session_state.support is None:
                    st.session_state.support = max(0, min(100, 35 + data["support_change"]))
                    st.session_state.public = max(0, min(100, 50 + data["public_change"]))
                else:
                    st.session_state.support = max(0, min(100, st.session_state.support + data["support_change"]))
                    st.session_state.public = max(0, min(100, st.session_state.public + data["public_change"]))

                # Progress updates
                st.session_state.chamber_progress = max(0, min(100,
                    st.session_state.chamber_progress + data["chamber_progress_change"]))

                st.session_state.reelection_risk += max(0, data["reelection_risk"])

                reelection_chance = calc_reelection_chance()
                update_trends(reelection_chance)
                st.session_state.history.append((action, narrative))
                st.session_state.turn += 1

                # ---- Outcome checks ----
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
    # ---- GAME OVER VIEW ----
    st.header("📊 Final Results")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Support", f"{st.session_state.support}%")
    with col2:
        st.metric("Public Approval", f"{st.session_state.public}%")
    with col3:
        st.metric("Chamber Progress", f"{st.session_state.chamber_progress}%")

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
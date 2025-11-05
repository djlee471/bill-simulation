import streamlit as st
import json
import pandas as pd
import matplotlib.pyplot as plt
import os
from openai import OpenAI

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
house_D = st.sidebar.slider("House Democrats", 0, 435, 218, 1, key="house_d_slider")
house_R = 435 - house_D
st.sidebar.caption(f"House Republicans: **{house_R}** (Total = 435)")

senate_D = st.sidebar.slider("Senate Democrats", 0, 100, 51, 1, key="senate_d_slider")
senate_R = 100 - senate_D
st.sidebar.caption(f"Senate Republicans: **{senate_R}** (Total = 100)")

house_control = "Democrats" if house_D > house_R else "Republicans"
senate_control = "Democrats" if senate_D > senate_R else "Republicans"

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
    st.error("⚠️ OpenAI API key not found. Please set `OPENAI_API_KEY` in Streamlit Secrets.")
    st.stop()

# ------------------------------------------------------
# GAME EXPLAINER
# ------------------------------------------------------
with st.expander("📘 How to Play & Win"):
    st.markdown(
        """
### 🎯 Objective
Advance your bill through Congress while keeping your reelection chances high.  
You have **8 turns** to navigate the process.

If your bill passes both chambers and you win reelection → **Full Victory**.  
If it passes one chamber → **Partial Win**.  
If you lose reelection or stall → **Costly or Stalled Outcome**.

| Rank | Outcome | Description |
|------|----------|-------------|
| 1️⃣ | 🏆 **Full Victory** | Passed both chambers + won reelection. |
| 2️⃣ | ✅ **Political Win** | Passed your chamber + won reelection. |
| 3️⃣ | 😬 **Costly Victory** | Passed but lost reelection. |
| 4️⃣ | ❌ **Stalled Bill** | Failed to advance before 8 turns or support < 20%. |

### 🧠 Strategy Tips
- Align moves with your **district lean** and **chamber control**.  
- Risky actions speed up progress but raise reelection risk.  
- Consensus actions protect approval but may slow advancement.  
- Track:  
  - 🏛 **Support in Chamber** = share of legislators backing your bill.  
  - 📊 **Public Support in District** = voter sentiment in your district.  
  - 🗳 **Reelection Chance** = calculated each turn.  
  - 📈 **Progress** = procedural advancement toward passage.  
        """
    )

# ------------------------------------------------------
# INITIAL STATE
# ------------------------------------------------------
if "turn" not in st.session_state:
    st.session_state.turn = 1
    st.session_state.support = None   # GPT sets after Turn 1
    st.session_state.public = 50
    st.session_state.house_progress = 0
    st.session_state.senate_progress = 0
    st.session_state.reelection_risk = 0
    st.session_state.history = []
    st.session_state.trends = pd.DataFrame(
        columns=["Turn", "Support", "Public", "ReelectionRisk", "ReelectionChance"]
    )
    st.session_state.game_over = False
    st.session_state.input_counter = 0

# ------------------------------------------------------
# GPT SIMULATION ENGINE
# ------------------------------------------------------
def gpt_simulate(action_text):
    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You are a political simulation engine modeling the U.S. Congress. "
        "Predict how congressional support, public approval, House and Senate progress, "
        "and reelection risk change this turn. "
        "Use realistic but gameplay-friendly magnitudes: "
        "support ±5–15, public ±5–10, progress +10–25, reelection risk +0–10. "
        "Consider partisanship, chamber control, and district lean. "
        "Return a short narrative followed by a JSON block with numeric updates. "
        "On the first turn, interpret the member's action as the bill introduction or early positioning. "
        "Set realistic starting values for support (initial coalition strength) and public approval — "
        "some new bills start below 50% support, especially if partisan or controversial."
    )

    user_prompt = f"""
Member info:
- Chamber: {your_chamber}
- Party: {your_party}
- District Lean: {district_lean}

Chamber Composition:
- House: {house_D} D / {house_R} R (Control: {house_control})
- Senate: {senate_D} D / {senate_R} R (Control: {senate_control})

Current stats:
- Support: {st.session_state.support}
- Public Approval: {st.session_state.public}
- House Progress: {st.session_state.house_progress}
- Senate Progress: {st.session_state.senate_progress}
- Reelection Risk: {st.session_state.reelection_risk}

Action this turn: {action_text}

Respond with a short paragraph (≤150 words) describing what happens,  
then output a JSON object like:
{{"support_change": int, "public_change": int, "house_progress_change": int, "senate_progress_change": int, "reelection_risk": int}}
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
                house_progress_change=0, senate_progress_change=0,
                reelection_risk=0
            )
        return text, data
    except Exception as e:
        return f"⚠️ GPT error: {e}", dict(
            support_change=0, public_change=0,
            house_progress_change=0, senate_progress_change=0,
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
                )]
            ),
        ],
        ignore_index=True,
    )

def plot_trends(df):
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(df["Turn"], df["Support"], label="Support")
    ax.plot(df["Turn"], df["Public"], label="Public Approval")
    ax.plot(df["Turn"], df["ReelectionChance"], label="Reelection Chance")
    ax.set_xlabel("Turn")
    ax.set_ylabel("Score")
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.4)
    st.pyplot(fig)

# ------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------
if not st.session_state.game_over:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"Turn {st.session_state.turn} of 8")
        support_display = st.session_state.support if st.session_state.support is not None else 0
        st.write(f"**Support in Chamber:** {support_display}% **Public Support in District:** {st.session_state.public}%")
        if st.session_state.support is None:
            st.caption("First-turn actions establish your initial coalition strength.")
    with c2:
        overall = (st.session_state.house_progress + st.session_state.senate_progress) / 2
        st.metric("Overall Progress", f"{overall:.0f}%")

    st.markdown("### Bill Progress by Chamber")
    a, b = st.columns(2)
    with a:
        st.write(f"🏠 **House:** {st.session_state.house_progress}% complete")
        st.progress(st.session_state.house_progress / 100)
    with b:
        st.write(f"🏛 **Senate:** {st.session_state.senate_progress}% complete")
        st.progress(st.session_state.senate_progress / 100)

    reelection_chance = calc_reelection_chance()
    st.metric("🗳️ Projected Reelection Chance", f"{reelection_chance:.0f}%")

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

            # Progress updates remain independent
            st.session_state.house_progress = max(0, min(100,
                st.session_state.house_progress + data["house_progress_change"]))
            st.session_state.senate_progress = max(0, min(100,
                st.session_state.senate_progress + data["senate_progress_change"]))

            st.session_state.reelection_risk += max(0, data["reelection_risk"])

            # Chamber interdependence bonus
            if your_chamber == "House" and st.session_state.house_progress >= 100 and st.session_state.senate_progress < 100:
                st.session_state.senate_progress = min(100, st.session_state.senate_progress + 5)
            elif your_chamber == "Senate" and st.session_state.senate_progress >= 100 and st.session_state.house_progress < 100:
                st.session_state.house_progress = min(100, st.session_state.house_progress + 5)

            reelection_chance = calc_reelection_chance()
            update_trends(reelection_chance)
            st.session_state.history.append((action, narrative))
            st.session_state.turn += 1

            # ---- Outcome checks ----
            if st.session_state.house_progress >= 100 and st.session_state.senate_progress >= 100:
                if reelection_chance >= 50:
                    st.session_state.game_over = True
                    st.success("🏆 Full Victory — Passed both chambers and won reelection.")
                else:
                    st.session_state.game_over = True
                    st.warning("😬 Costly Victory — Passed Congress but lost reelection.")
            elif your_chamber == "House" and st.session_state.house_progress >= 100 and st.session_state.senate_progress < 100:
                st.info("✅ The House has passed your bill! Now focus on the Senate ...")
            elif your_chamber == "Senate" and st.session_state.senate_progress >= 100 and st.session_state.house_progress < 100:
                st.info("✅ The Senate has passed your bill! Can you persuade the House before the session ends?")
            elif st.session_state.turn > 8 or (st.session_state.support is not None and st.session_state.support < 20):
                st.session_state.game_over = True
                st.error("❌ Stalled Bill — Your legislation failed to advance before the session ended.")

            st.write(narrative)
            plot_trends(st.session_state.trends)

            st.session_state.input_counter += 1
        else:
            st.warning("⚠️ Please enter an action first!")

else:
    # ---- GAME OVER VIEW ----
    st.header("📊 Final Results")
    st.metric("Support", st.session_state.support)
    st.metric("Public Approval", st.session_state.public)
    st.metric("House Progress", st.session_state.house_progress)
    st.metric("Senate Progress", st.session_state.senate_progress)

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

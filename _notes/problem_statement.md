# Vapi Technical Take-Home: Voice Agent Optimization (ML)

As part of our evaluation process, we’d like you to complete a technical take-home assignment focused on voice agent optimization using machine learning. Please see the details below. **Submit within 24 hours of receiving this email.**

---

## Background

Vapi enables businesses to deploy voice AI agents for tasks like appointment scheduling, customer support, and sales. A Vapi agent consists of:

- **System prompt** — Instructions that define the agent’s personality, goals, and behavior
- **Model configuration** — LLM provider, temperature, max tokens, etc.
- **Voice settings** — TTS provider and voice selection
- **Transcriber settings** — STT provider and configuration
- **Analysis settings** — How to evaluate call success

Today, improving an agent is a manual process: listen to recorded calls, identify where the agent struggled, tweak the prompt, deploy, and repeat. This is time-consuming and doesn’t scale when you have hundreds of agents or need to optimize for nuanced conversational quality.

---

## The Challenge

Build a **machine learning–driven system** that can automatically improve a Vapi voice agent’s performance through iterative evaluation and optimization.

### What this means

Your system should be able to:

1. Run test conversations against an agent (using the Vapi API)
2. Evaluate performance based on criteria you define
3. Identify weaknesses in the current agent configuration
4. Generate improvements to the agent (prompt, settings, etc.) using ML methods
5. Validate that changes actually help before accepting them
6. Iterate until performance plateaus or a target is reached

---

## Example use cases

**Pick one to focus on:**

| Use case | Focus |
|----------|--------|
| Dental office scheduler | Book appointments, handle rescheduling, answer questions about services |
| Sales development rep | Qualify leads, handle objections, book demos |
| Customer support | Troubleshoot issues, escalate when needed, maintain satisfaction |
| Restaurant reservation | Handle bookings, dietary restrictions, waitlist management |

---

## Requirements

- Use the **Vapi API** to create agents and run conversations
- Optimization must be **automated with a machine learning approach** (no human in the loop per iteration)
- **Demonstrate measurable improvement** from starting to final agent
- Your system should be **reproducible** (we can run it and see similar results)

---

## Deliverables

| Deliverable | Description |
|-------------|-------------|
| **Working code** | Clone, setup, run. Should work. |
| **Documentation** | What’s your ML approach? How do we use it? What are the tradeoffs? |
| **Results** | Show us before/after. Quantify the improvement. |

---

## Vapi API reference

- **Documentation:** [https://docs.vapi.ai](https://docs.vapi.ai)

### Key endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /assistant` | Create or update an assistant configuration |
| `POST /call` | Initiate a call to test the assistant |
| `GET /call/{id}` | Retrieve call details, transcript, and recording |

### Useful features

- **`analysisPlan`** — Configure how Vapi evaluates each call (structured data extraction, success criteria)
- **`artifact.transcript`** — Full conversation transcript
- **`artifact.recording`** — Audio recording URL
- **`artifact.messages`** — Structured message history with timestamps

If you need API credits beyond the free tier, let us know.

---

## Evaluation criteria

| Criteria | Weight | What we’re looking for |
|----------|--------|-------------------------|
| Problem understanding | 20% | Did you identify the right things to optimize? Do your metrics capture what matters? |
| Technical implementation | 30% | Does it work? Is the code reasonable? Can we run it? |
| Optimization approach | 25% | Is your ML method principled? Does it actually improve the agent? |
| Engineering judgment | 15% | Did you scope appropriately? Do tradeoffs make sense? |
| Communication | 10% | Can we understand what you did and why? |

---

## Practical notes

- **Time** — This is scoped for ~4 hours of focused work. We’re not expecting a production system.
- **AI/ML tools** — Use whatever you want — scikit-learn, PyTorch, TensorFlow, or platform tools like Claude, Cursor, Copilot, ChatGPT.
- **Ambiguity** — There’s no single right answer. Make reasonable assumptions and document them.
- **Creativity** — Novel approaches are welcome, but working beats clever.

---

## Submission

1. Push your code to a **GitHub** repository
2. Include **setup instructions** that actually work
3. Send us the link and submit here, and **cc** [nikhil@vapi.ai](mailto:nikhil@vapi.ai) and [tejas@vapi.ai](mailto:tejas@vapi.ai)

---

*Questions? Email us.*

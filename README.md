# 🎓 Year 5 CS/IT Telegram Supergroup Assistant Bot

A production-grade, asynchronous Telegram Bot built for university students in **Year 5 Semester 1 studying IT and Computer Science**. The bot operates seamlessly inside a Telegram Forum Supergroup with dedicated sub-topics (threads) for eight specialized university subjects plus a General administrative topic.

---

## 🏛️ Curriculum & Topic Coverage

The bot dynamically injects deep domain knowledge, mathematical formulation, and tailored system prompts based on the active Telegram forum topic (`message_thread_id`):

| Course Key | Course Name | Subject Code | Focus Areas |
| :--- | :--- | :--- | :--- |
| `AI` | **Artificial Intelligence** | CS501 | A*, Alpha-Beta, MDPs, Q-Learning, PyTorch neural networks |
| `CLOUD` | **Cloud Computing** | CS502 | AWS/GCP, VPC, Subnets, Docker, Kubernetes manifests, Terraform |
| `DATA_MINING` | **Data Mining** | CS503 | CRISP-DM, Apriori, FP-Growth, DBSCAN, XGBoost, Scikit-Learn |
| `IMAGE_PROC` | **Image Processing** | CS504 | 2D Fourier transforms, Canny edge detection, OpenCV, Morphological ops |
| `INFO_SEC` | **Information Security** | CS505 | AES-GCM, RSA, ECC, SHA-256, HMAC, PKI/X.509, OWASP Top 10 |
| `NET_SEC` | **Network Security** | CS506 | Wireshark PCAPs, Scapy, Snort rules, TLS 1.3 handshakes, WireGuard |
| `NLP` | **Natural Language Processing**| CS507 | BPE Tokenizers, Word2Vec, Attention, Transformers, BERT, LLMs |
| `IT_PM` | **IT Project Management** | CS508 | Scrum, Sprint Burndown, Gantt, Critical Path (CPM), COCOMO II |
| `GENERAL` | **General / Administrative** | GEN500 | Semester milestones, exam schedules, cross-course coordination |

---

## 🚀 Key Architectural Highlights

1. **Topic-Thread Context Awareness:**
   - Detects `message_thread_id` on every event.
   - Automatically injects course-specific personas and domain instructions without manual switching.
   - Includes `/get_id` for instant discovery and `/set_topic` for dynamic database binding.

2. **In-Memory Document Ingestion & Parsing:**
   - **Office & Slides:** PDF (`.pdf`), Word (`.docx`, `.doc`), PowerPoint (`.pptx`, `.ppt`), Excel (`.xlsx`, `.xls`).
   - **Academic & Labs:** Jupyter Notebooks (`.ipynb` with markdown, code, and error tracebacks), LaTeX (`.tex`).
   - **OpenDocument & Rich Text:** `.odt`, `.ods`, `.odp`, `.rtf`.
   - **Data & Tabular:** CSV (`.csv`), TSV (`.tsv`), JSON (`.json`), YAML (`.yaml`, `.yml`), XML (`.xml`), HTML (`.html`).
   - **Source Code:** Python (`.py`), C/C++ (`.c`, `.cpp`), Java (`.java`), C# (`.cs`), Go (`.go`), Rust (`.rs`), TypeScript/JavaScript (`.ts`, `.js`), SQL (`.sql`), Shell (`.sh`, `.ps1`), R (`.r`).
   - Decodes entirely in memory without writing temporary files to disk; generates executive summaries, formulas, lab steps, and exam questions.

3. **Academic Khmer & English Translation:**
   - Translates complex slides and texts into formal Academic Khmer (`ភាសាខ្មែរបែបសិក្សាស្រាវជ្រាវ`) or polished English.
   - **Strict Terminology Retention**: Retains standard CS/IT terms in English (e.g., *VPC*, *Tokenizer*, *Gradient Descent*, *Eigenvalue*, *Docker*, *Subnet*).

4. **Lab Code & Algorithmic Debugger (`/debug`):**
   - Resolves tensor dimension mismatches, networking bugs, runtime errors, and algorithm logic flaws.
   - Outputs Root Cause Analysis, conceptual theory, and fully commented, robust code.

5. **Academic Message Polisher (`/fix` or `/refactor`):**
   - Generates 3 polished versions: Formal Professor Inquiry, Group Project Collaboration, and Technical Presentation.

6. **Deadline & Task Management (`aiosqlite` + `JobQueue`):**
   - Natural date parsing (`/due 2026-10-25 23:59 Lab 3`, `/due tomorrow 5pm`, `/due in 3 days`).
   - Automated scheduled reminders posted directly into the respective forum topic at **24 hours**, **6 hours**, and **1 hour** before deadlines.

7. **Production Engineering:**
   - Handles Telegram's 4096-character limit via intelligent chunking without breaking HTML tags or code blocks.
   - Built-in sliding-window user rate limiting to prevent API exhaustion.
   - Fully containerized with multi-stage Docker build and persistent SQLite volume.

---

## 📂 Project Directory Structure

```text
TelegramBot/
├── bot.py                     # Main application entry point & lifecycle
├── config/
│   ├── __init__.py
│   ├── settings.py            # Pydantic v2 settings & topic mapper
│   └── prompts.py             # Course system prompts & academic personas
├── database/
│   ├── __init__.py
│   ├── db.py                  # aiosqlite asynchronous connection pool & queries
│   └── models.py              # Data models (Deadline, TopicBinding)
├── handlers/
│   ├── __init__.py
│   ├── command_handlers.py    # All slash commands (/start, /fix, /debug, /due, etc.)
│   ├── document_handlers.py   # In-memory document ingestion (.pdf, .docx, .pptx)
│   ├── text_handlers.py       # Topic-aware natural language QA & bot mentions
│   └── error_handlers.py      # Global error handling and logging
├── services/
│   ├── __init__.py
│   ├── llm_engine.py          # Google Gemini async client & prompt dispatch
│   ├── document_parser.py     # In-memory extractors for PDF, Word, PowerPoint
│   ├── date_parser.py         # Resilient human date/time parser
│   └── reminder_service.py    # Background scheduled deadline checker
├── utils/
│   ├── __init__.py
│   ├── telegram_helpers.py    # 4096-char chunking, HTML escaping, safe replies
│   └── rate_limiter.py        # Sliding-window rate limiter per user
├── Dockerfile                 # Production multi-stage Docker container
├── docker-compose.yml         # Container orchestration with SQLite volume mount
├── requirements.txt           # Pinned Python package dependencies
├── pyproject.toml             # Project metadata
├── .env.example               # Environment variables template
└── README.md                  # System manual and deployment documentation
```

---

## 🛠️ Step-by-Step Installation & Setup

### 1. Obtain Prerequisites

1. **Telegram Bot Token:**
   - Open Telegram and message [@BotFather](https://t.me/BotFather).
   - Use `/newbot` to create your bot and copy the `TELEGRAM_BOT_TOKEN`.
   - In BotFather, send `/setprivacy` -> Select your bot -> Choose **Disable** (so the bot can read messages in group topics when addressed).
   - In BotFather, send `/setjoingroups` -> Select your bot -> Choose **Enable**.

2. **Google Gemini API Key:**
   - Visit [Google AI Studio](https://aistudio.google.com/) and create a free API key.

3. **Telegram Forum Supergroup Setup:**
   - Create a Telegram Supergroup for your Year 5 cohort.
   - In Group Settings, enable **Topics** (Forums).
   - Add your bot to the supergroup as an **Administrator** with permission to send messages and manage topics.
   - Create 8 topics for the courses plus 1 General topic:
     1. `Artificial Intelligence`
     2. `Cloud Computing`
     3. `Data Mining`
     4. `Image Processing`
     5. `Information Security`
     6. `Network Security`
     7. `Natural Language Processing`
     8. `IT Project Management`
     9. `General & Administrative`

---

### 2. Environment Configuration

Clone or navigate to the repository directory and copy `.env.example`:

```bash
cp .env.example .env
```

Open `.env` in an editor and enter your credentials:

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Prioritized LLM Providers Array (first one is tried first)
LLM_PROVIDER_ORDER=openrouter,opencode_zen

# OpenRouter Configuration (https://openrouter.ai/keys)
OPENROUTER_API_KEY=sk-or-v1-your_openrouter_key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=google/gemini-2.5-flash

# OpenCode Zen Configuration
OPENCODE_ZEN_API_KEY=your_opencode_zen_key
OPENCODE_ZEN_BASE_URL=https://api.opencodezen.com/v1
OPENCODE_ZEN_MODEL=gpt-4o-mini

TIMEZONE=Asia/Phnom_Penh
ADMIN_USER_IDS=123456789
```

#### Mapping Forum Topics:
Inside each topic in Telegram, type `/get_id`. The bot will reply with the exact `Message Thread ID`. You can either:
1. Paste the thread IDs directly into `.env`:
   ```dotenv
   TOPIC_THREAD_AI=12
   TOPIC_THREAD_CLOUD=15
   TOPIC_THREAD_DATA_MINING=18
   ...
   ```
2. **Or bind dynamically at runtime**: Type `/set_topic AI` inside the AI topic (Admin only), and the bot will store the mapping in SQLite!

---

### 3. Deployment Options

#### Option A: Docker & Docker Compose (Recommended for Production)

Ensure Docker and Docker Compose are installed, then run:

```bash
# Build and launch container in background
docker compose up -d --build

# View real-time logs
docker compose logs -f

# Check container status
docker compose ps

# Stop the container
docker compose down
```

The database is persisted in `./data/bot.db` on your host machine.

---

#### Option B: Direct Python Execution (Local / VPS)

1. **Create and activate a virtual environment:**

```bash
# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell):
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. **Install dependencies:**

```bash
pip install -r requirements.txt
```

3. **Start the bot:**

```bash
python bot.py
```

---

#### Option C: AWS EC2 (24/7)

The bot uses long polling and SQLite, so it runs as a single always-on EC2 instance (no inbound ports needed besides SSH).

1. Launch an **Ubuntu 24.04** instance (`t3.micro` is enough) with a 16 GB gp3 volume, a security group allowing SSH only from your IP, and paste [`deploy/ec2-user-data.sh`](deploy/ec2-user-data.sh) as **User data**. It installs Docker, adds swap, and clones this repo to `/opt/telegram-bot`.
2. Copy your secrets and start the bot:

```bash
scp .env ubuntu@<EC2_PUBLIC_IP>:/opt/telegram-bot/.env
ssh ubuntu@<EC2_PUBLIC_IP> "chmod 600 /opt/telegram-bot/.env && cd /opt/telegram-bot && docker compose up -d --build"
```

3. Deploy updates after pushing to GitHub:

```bash
ssh ubuntu@<EC2_PUBLIC_IP> /opt/telegram-bot/deploy/update.sh
```

> Only one instance may poll Telegram per bot token. Stop any local `python bot.py` before starting the server copy, or both will hit `409 Conflict`.

---

## 📖 Command Reference & Usage Examples

### 1. Document Summarization & Data Ingestion
- Upload any lecture slide, dataset, or notebook (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.ipynb`, `.csv`) into any course topic.
- **Excel Spreadsheets (`.xlsx`, `.xls`):** Analyzes sheets, column schemas, data distribution, and key statistics.
- **Jupyter Notebooks (`.ipynb`):** Extracts markdown instructions, code cells, outputs, and pinpointed error tracebacks.
- **PowerPoint & Word (`.pptx`, `.docx`):** Digests slides, speaker notes, formulas, and lab instructions.
- The bot outputs:
  - 📌 Executive Summary
  - 🧠 Key Concepts & Formal Definitions
  - 📐 Mathematical Formulas (LaTeX formatted)
  - 💻 Practical Lab Tasks & Code requirements
  - 🎯 Sample Exam / Viva Questions

### 2. Academic Translation (`/translate`)
- Reply to any message or document with `/translate` (or `/translate kh`) to translate into Academic Khmer, preserving technical terms like *Tokenizer*, *VPC*, *Gradient Descent*.
- Reply with `/translate en` to refine into formal Academic English.

### 3. Lab Code Debugger (`/debug`)
- Reply to an error message, stack trace, or buggy snippet with `/debug`.
- Or write `/debug <code snippet>`:
  ```text
  /debug
  import torch
  A = torch.randn(32, 128)
  B = torch.randn(64, 128)
  C = torch.matmul(A, B)
  ```
- The bot returns Root Cause Analysis (matrix dimension mismatch), mathematical reason, and the corrected snippet with comments.

### 4. Academic Message Polisher (`/fix`)
- Reply to a draft message with `/fix` to generate:
  - 👔 Formal Professor Inquiry
  - 🤝 Peer & Group Project Coordination
  - 📑 Formal Presentation / Technical Report

### 5. Deadline Tracker (`/due`, `/deadlines`, `/done`)
- **Add Deadline:**
  ```text
  /due 2026-10-25 23:59 Final Project Milestone 1
  /due tomorrow 5pm Homework Lab 4
  /due in 3 days Research Paper Summary
  /due friday 23:59 Network Security Lab Report
  ```
- **View Deadlines:**
  Type `/deadlines` inside any topic to see upcoming tasks for that course, or in General for all courses.
- **Complete Task:**
  Type `/done <task_id>` (e.g. `/done 3`).
- **Automated Alerts:**
  The background scheduler automatically triggers notices at **24h**, **6h**, and **1h** before deadlines directly in the forum topic.

---

## 🔒 Security & Best Practices

- **Zero-Disk Document Extraction:** Documents are decoded in memory (`io.BytesIO`) and garbage-collected immediately.
- **Non-Root Docker Execution:** The Docker container runs as an unprivileged user `appuser` (UID 1000).
- **Rate-Limiting:** Sliding-window limiter protects Gemini quotas against spam or accidental flood loops.
- **Fail-Safe HTML Delivery:** If Telegram rejects HTML formatting due to unexpected character combinations, the bot automatically retries and delivers as clean plain text.

---

## 📄 License
MIT License. Built for university computer science and IT academic cohorts.

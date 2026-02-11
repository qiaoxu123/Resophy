## Installation


<div align=center>
  <img src="https://github.com/user-attachments/assets/73d25cfa-5791-4b54-a131-d816f51afebb" >
  <div style="margin-top:8px; color: #555; font-size: 16px;">
    Resophy adopts a frontend-backend separated architecture
  </div>
</div>


- [Installation](#installation)
    - [1. Architecture Overview](#1-architecture-overview)
    - [1.1. Resophy Server (Main Service)](#11-resophy-server-main-service)
    - [1.2. AI End (Optional - AI Server)](#12-ai-end-optional---ai-server)
  - [2. Deploy Resophy Server](#2-deploy-resophy-server)
    - [2.1 Prerequisites](#21-prerequisites)
    - [2.2 Configuration](#22-configuration)
    - [2.3 Build and Run](#23-build-and-run)
    - [2.4 Initialize Database](#24-initialize-database)
    - [2.5 Access and Login](#25-access-and-login)
  - [3. Install Resophy AI End (Optional)](#3-install-resophy-ai-end-optional)
    - [3.1 Deploy MinerU](#31-deploy-mineru)
    - [3.2 Configure LLM Server](#32-configure-llm-server)


#### 1. Architecture Overview

Resophy is deployed as a **Docker-based server** with multi-user support, MySQL persistent storage, and Flarum-based user authentication. It consists of two independent parts:

#### 1.1. Resophy Server (Main Service)

- **Tech Stack**: HTML + CSS + JavaScript + Python Flask + MySQL
- **Features**: Contains all core functionalities of Resophy
  - Multi-user support with Flarum authentication
  - Paper management (upload, classification, search)
  - Literature management (tree classification, full-text search, metadata management)
  - Import/Export (Zotero import, JSON export)
  - Reading history tracking
  - User interface and interactions
- **Deployment**: Docker container connecting to MySQL and Flarum services
- **Dependencies**: Managed via Docker image (no manual installation required)

#### 1.2. AI End (Optional - AI Server)

- **Features**: Provides AI-enhanced functionalities
  - AI Translation (PDF bilingual translation)
  - AI Interpretation (Deep paper analysis)
  - Daily arXiv (Intelligent paper filtering)
- **Components**:
  - **LLM Server**: Deployed using lmdeploy or vllm (recommended: Qwen3-4B-Instruct)
  - **MinerU Server**: For PDF to Markdown parsing (MinerU2.5-2509-1.2B model)
- **Deployment Requirements**:
  - Requires GPU support (CUDA)
  - Can be deployed on a different machine from the Resophy server
  - Communicates with Resophy server through HTTP API
- **Communication Method**: Resophy server calls AI end services through HTTP API


### 2. Deploy Resophy Server

#### 2.1 Prerequisites

Resophy is designed to run within an existing infrastructure that includes:

- **Docker & Docker Compose** installed
- **MySQL 8.4** (e.g. managed by 1Panel or standalone)
- **Flarum** forum instance (provides user accounts and authentication)
- A shared Docker network connecting all services (default: `1panel-network`)

> **Note**: MySQL and Flarum are expected to be running as separate containers or services. Resophy connects to them over the shared Docker network.

#### 2.2 Configuration

1. Clone the repository:

```bash
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy
```

2. Copy the environment template and fill in your values:

```bash
cp .env.example .env
```

3. Edit `.env` with your actual credentials:

```bash
# --- Resophy MySQL Database ---
DB_HOST=your-mysql-container-name    # e.g. 1Panel-mysql-c3Jl
DB_PORT=3306
DB_NAME=resophy
DB_USER=resophy
DB_PASSWORD=your_secure_password

# --- Flarum Database (read-only, for authentication) ---
FLARUM_DB_HOST=your-mysql-container-name
FLARUM_DB_NAME=your_flarum_db_name
FLARUM_DB_USER=your_flarum_db_user
FLARUM_DB_PASSWORD=your_flarum_db_password
FLARUM_DB_PREFIX=flarum_
FLARUM_API_URL=http://your-flarum-container:8000

# --- App ---
SECRET_KEY=generate-a-random-string-here
```

4. Update `docker-compose.yml` if your container names or network differ from the defaults.

#### 2.3 Build and Run

```bash
# Build and start (foreground, to see logs)
docker compose up --build

# Or run in detached mode
docker compose up --build -d

# View logs
docker compose logs -f resophy

# Stop
docker compose down
```

The service will be available at `http://localhost:7191`.

#### 2.4 Initialize Database

The database schema is **automatically created** on first startup. Resophy runs `deploy/init.sql` to create all required tables (`papers`, `user_papers`, `user_categories`, `user_settings`, `user_reading_history`, `user_reading_list`) if they don't already exist.

**Before first use**, create the `resophy` database in your MySQL instance:

```sql
CREATE DATABASE IF NOT EXISTS resophy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'resophy'@'%' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON resophy.* TO 'resophy'@'%';
FLUSH PRIVILEGES;
```

#### 2.5 Access and Login

1. Open your browser and visit `http://your-server-ip:7191`
2. You will be redirected to the login page
3. Log in with your **Flarum forum credentials** (username and password)
4. Resophy authenticates against the Flarum users table — no separate registration is needed

> **Note**: If you need to create new user accounts, register them through your Flarum forum instance first.

---

### 3. Install Resophy AI End (Optional)

> **Important Note**: AI servers can be deployed on different machines from the Resophy server. The Resophy server only needs the API addresses of these AI servers to use AI features. You can deploy AI servers on machines with GPUs according to your resources, while the Resophy server can be deployed on any machine.


On the machine where you need to deploy MinerU and LLM servers (recommended: machines with GPU), install the server end version:

<details open>
<summary><strong>Linux Installation</strong></summary>

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Clone repository
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy
# Create virtual environment (recommended)
uv venv
source .venv/bin/activate
# Install server end version (includes AI server dependencies)
uv pip install -e ".[server]"
```

</details>

<details close>
<summary><strong>Mac Installation</strong></summary>

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc
# Clone repository
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy
# Create virtual environment (recommended)
uv venv
source .venv/bin/activate
# Install server end version (includes AI server dependencies)
uv pip install -e ".[server]"
```

</details>

</details>

<details close>
<summary><strong>Windows Installation</strong></summary>
Using PowerShell as an example


```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Please replace USERNAME below with your username
[System.Environment]::SetEnvironmentVariable("Path", "$env:Path;C:\Users\USERNAME\.local\bin", [System.EnvironmentVariableTarget]::User)
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', [System.EnvironmentVariableTarget]::User)
uv --version
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.venv\Scripts\activate.ps1
uv pip install -e ".[server]"
```

</details>

Resophy's AI features (**AI Translation**, **AI Interpretation**, **Daily arXiv**) depend on the following services:

- **LLM API Access**: For paper translation, interpretation generation, and arXiv paper intelligent analysis
- **MinerU Service**: For parsing PDFs into Markdown format, supporting high-quality document structure recognition

The following are detailed deployment steps:

#### 3.1 Deploy MinerU

MinerU is used to parse PDF documents into structured Markdown format and is the foundation of the AI interpretation feature.

You have two options for using MinerU:

**Option 1: Use MinerU Official Cloud API (Recommended for Quick Start)**

This is the easiest way to get started without GPU requirements:

1. **Get API Token**: Visit [https://mineru.net/](https://mineru.net/) to register and get your API token
2. **Configure in Resophy**:
   - Go to Settings → Agentic tab
   - Under "MinerU Mode", select "Cloud API"
   - Enter your API token
   - Click "Test" to verify the connection
   - Save settings

That's it! You can now use MinerU's cloud service for PDF parsing without any local deployment.

**Option 2: Deploy MinerU Locally (Requires GPU)**

If you prefer to deploy MinerU on your own server:

**Step1: Download MinerU2.5 Model**

MinerU requires downloading the corresponding model files. Model files should be placed in the `ai_server/` directory:

```bash
mkdir ai_server
# download from huggingface
huggingface-cli download opendatalab/MinerU2.5-2509-1.2B --local-dir ai_server/MinerU2.5-2509-1.2B

# or download from modelscope (for chinese users)
uv add modelscope
modelscope download opendatalab/MinerU2.5-2509-1.2B --local_dir ai_server/MinerU2.5-2509-1.2B
```

**Step2. Start MinerU vLLM Server**

```bash
mineru-vllm-server \
  --model ai_server/MinerU2.5-2509-1.2B \
  --host 0.0.0.0 \
  --port 6001
```

MinerU will start an API server at `http://0.0.0.0:6001` for parsing PDFs into Markdown format.

**Step3. Configure in Resophy**:
- Go to Settings → Agentic tab
- Under "MinerU Mode", select "Local Deployment"
- Enter your MinerU server URL (e.g., `http://0.0.0.0:6001`)
- Click "Test" to verify the connection
- Save settings

> **Note**: MinerU server requires GPU support. If using CPU inference, please refer to the [MinerU official documentation](https://github.com/opendatalab/MinerU?tab=readme-ov-file#local-deployment) for configuration.

#### 3.2 Configure LLM Server

Resophy's AI features require access to LLM API. You can use one of the following two methods:

**Method 1: Use Locally Deployed LLM (Recommended)**

Deploy a local LLM model using `lmdeploy` or `vllm`. In our actual testing, using `Qwen3-4B-Instruct` as the base model can achieve good results


**Step1: Download Model Weights**

```bash
# download from huggingface
mkdir ai_server
huggingface-cli download Qwen/Qwen3-4B-Instruct-2507 --local-dir ai_server/Qwen3-4B-Instruct-2507

# or download from modelscope (for chinese users)
# If you installed resophy[server], modelscope is already included
modelscope download Qwen/Qwen3-4B-Instruct-2507 --local_dir ai_server/Qwen3-4B-Instruct-2507
```

**Step2: Start LLM Server**

```bash
# Single GPU deployment example (4B model)
vllm serve ai_server/Qwen3-4B-Instruct-2507 \
  --api-key token-abc123 \
  --host 0.0.0.0 \
  --port 6002 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.6 \
```

**Method 2: Use Remote LLM API**

If you use remote API services such as OpenAI, DeepSeek, OpenRouter, etc., you can directly configure the API address and key in Resophy settings without local deployment

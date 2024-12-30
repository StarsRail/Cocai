# <img src="public/logo_light.png" width="36px" /> CoCai

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![JavaScript Style Guide](https://img.shields.io/badge/code_style-standard-brightgreen.svg)](https://standardjs.com)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2FStarsRail%2FCocai&count_bg=%2379C83D&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=hits&edge_flat=false)](https://hits.seeyoufarm.com)

A chatbot that plays Call of Cthulhu (CoC) with you, powered by AI.

<img width="866" alt="image" src="https://github.com/user-attachments/assets/59b159f8-ace5-4df0-bb4a-a33dff190d99">

[Video demo](https://www.youtube.com/watch?v=8wagQoMPOKY)

## Demo

Check out this transcript:

<img width="786" alt="image" src="https://github.com/user-attachments/assets/e039276c-d495-4596-b547-acfc66ce6a84">

In the first message, I asked Cocai to generate a character for me:

> Can you generate a character for me? Let's call him "Don Joe". Describe what kind of guy he is, then tabulate his stats.

Under the hood, Cocai used [Cochar](https://www.cochar.pl/). In the first couple of attempts, Cocai forgot to provide some required parameters. Cocai fixed that problem and successfully generated a character profile from Cochar.

Then, I asked Cocai what I -- playing the character of Mr. Don Joe -- can do, being stuck in a dark cave. It suggested a couple of options and described the potential outcomes associated with each choice.

I then asked Cocai to roll a skill check for me, Spot Hidden. Based on the chat history, Cocai was able to recall that Mr. Joe had a Spot Hidden skill of 85%. It rolled the dice, got a successful outcome, and took some inspiration from its 2nd response to progress the story.

Thanks to the chain-of-thought (CoT) visualization feature, you can unfold the tool-using steps and verify yourself that Cocai was indeed able to recall the precise value of Joe's Spot Hidden skill:

<img width="771" alt="image" src="https://github.com/user-attachments/assets/8ae52b80-b3c0-4978-9649-64039a5c113e">


## Usage

### Pre-requisites

There are a couple of things you have to do manually before you can start using the chatbot.

1. Clone the repository ([how](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)).
2. **Install the required binary, standalone programs**. These are not Python packages, so they aren't managed by `pyproject.toml`.
3. **Self-serve a text embedding model**. This model "translates" your text into numbers, so that the computer can understand you.
4. **Choose a way to serve a large language model (LLM)**. You can either use OpenAI's API or self-host a local LLM with Ollama.
5. **Initialize secrets**.

No need to explicitly install Python packages. `uv`, the package manager of our choice, will implicitly install the required packages when you boot up the chatbot for the first time.

#### Install the required binary programs

These are the binary programs that you need to have ready before running Cocai:
- Install [`just`](https://github.com/casey/just), a command runner. I use this because I always tend to forget the exact command to run.
- Written in Python, this project uses the Rust-based package manager [`uv`](https://docs.astral.sh/uv/). It does not require you to explicitly create a virtual environment.
- Install Docker. Cocai requires many types of databases, e.g. object storage and vector storage, along with some containerized applications. We need the `docker-compose` command to orchestrate these containers.
- As aforementioned, if you decide to self-host a LLM, install Ollama.
- If you ever want to run the chatbot the easy way (discussed later), you'll need `tmuxinator` and `tmux`.

If you are on macOS, you can install these programs using Homebrew:

```shell
brew install just uv ollama tmuxinator
brew install --cask docker
```

Optionally, also install [Stable Diffusion Web UI][sdwu]. This allows the chatbot to generate illustrations.

[sdwu]: https://github.com/AUTOMATIC1111/stable-diffusion-webui

#### Self-serve an embedding model

Ensure that you have a local Ollama server running:

```shell
ollama serve
```

and then:

```shell
ollama pull nomic-embed-text
```

#### Bring your own large language model (LLM)

The easiest (and perhaps highest-quality) way would be to provide an API key to OpenAI. Simply add `OPENAI_API_KEY=sk-...` to a `.env` file in the project root.

With the absence of an OpenAI API key, the chatbot will default to using [Ollama](https://ollama.com/download), a program that serves LLMs locally.
- Ensure that your local Ollama server has already downloaded the `llama3.1` model. If you haven't (or aren't sure), run `ollama pull llama3.1`.
- If you want to use a different model that does not support function-calling, that's also possible. Revert [this commit][tc], so that you can use the ReAct paradigm to simulate function-calling capabilities with a purely semantic approach.

[tc]: https://github.com/StarsRail/Cocai/commit/13d777767d1dd96024021c085247525ec52b79ba

#### Prepare secrets

Run `chainlit create-secret` to generate a JWT token. Follow the instructions to add the secret to `.env`.

Start serving minIO for the first time by running `minio server .minio/`. Then navigate to `http://127.0.0.1:57393/access-keys` and create a new access key. (You may need to log in first. The default credentials can be found in [their official documentation][mod].) Add the access key and secret key to `.env`:

[mod]: https://min.io/docs/minio/linux/reference/minio-server/settings/root-credentials.html#id1

```toml
MINIO_ACCESS_KEY="foo"
MINIO_SECRET_KEY="bar"
```

Optionally, if you want to enable the chatbot to search the internet, you can provide a Tavily API key. Add `TAVILY_API_KEY=...` to `.env`.

Optionally, if you prefer to use OpenAI ("GPT") as your LLM, add `OPENAI_API_KEY=...` to `.env`.

Optionally, if you prefer to use a hosted open LLM, you can try [Together.ai](https://www.together.ai/). Add `TOGETHER_AI_API_KEY=...` to `.env`.

### Running the Chatbot

There are 2 ways to start the chatbot, the easy way and the hard way.

In the easy way, **simply run `just serve-all`**. This will start all the required standalone programs and the chatbot in one go. Notes:
* **Use of multiplexer.** To avoid cluttering up your screen, we use a [terminal multiplexer][tmx] (`tmux`), which essentially divides your terminal window into panes, each running a separate program.
  The panes are defined in the file `tmuxinator.yaml`. [Tmuxinator](https://github.com/tmuxinator/tmuxinator) is a separate program that manages `tmux` sessions declaratively.
* **Production-oriented**. This `just serve-all` command is also used in our containerized setup, namely `Dockerfile`. For this reason, the commands in `tmuxinator.yaml` are oriented towards production use.
  For example, the chatbot doesn't listen on file changes to auto-reload itself, which could be a useful feature if you are tweaking the code frequently. If you want to enable auto-reloading:
  * modify the `tmuxinator.yaml` (but please don't commit to git), or just
  * run all commands manually (i.e., the hard way).

[tmx]: https://en.wikipedia.org/wiki/Terminal_multiplexer

<img width="1278" alt="image" src="https://github.com/user-attachments/assets/d7db810d-4de0-432d-87f2-affc14e1daa9">

In the hard way, you want to create a separate terminal for each command:
1. Start serving **Ollama** (for locally inferencing embedding & language models) by running `ollama serve`. It should be listening at `http://localhost:11434/v1`.
2. Start Docker containers by running `docker-compose up`. This includes:
   - **minIO** object database (for persisting data for our web frontend, including user credentials and chat history -- not thought chains, though)
   - **Arize Phoenix** platform (for debugging thought chains)
   - **Qdrant** vector database (for the chatbot's short-term memory -- this is implemented via `mem0`)
3. Optionally, to enable your AI Keeper to draw illustrations, start serving a "**Stable Diffusion web UI**" server with API support turned on by running `cd ../stable-diffusion-webui; ./webui.sh --api --nowebui --port 7860`.
  If Stable Diffusion is not running, the AI Keeper will still be able to generate text-based responses. It's just that it won't be able to draw illustrations.
4. Finally, start serving the **chatbot** by running `just serve`.

Either way, Cocai should be ready at `http://localhost:8000/chat/`. Log in with the dummy credentials `admin` and `admin`.

## Troubleshooting

If you see:

```
  File ".../llvmlite-0.43.0.tar.gz/ffi/build.py", line 142, in main_posix
    raise RuntimeError(msg) from None
RuntimeError: Could not find a `llvm-config` binary. There are a number of reasons this could occur, please see: https://llvmlite.readthedocs.io/en/latest/admin-guide/install.html#using-pip for help.
error: command '.../bin/python' failed with exit code 1
```

Then run:

```shell
brew install llvm
```

If your `uv run phoenix serve` command fails with:

```
Traceback (most recent call last):
  File "Cocai/.venv/bin/phoenix", line 5, in <module>
    from phoenix.server.main import main
  File "Cocai/.venv/lib/python3.11/site-packages/phoenix/__init__.py", line 12, in <module>
    from .session.session import (
  File ".venv/lib/python3.11/site-packages/phoenix/session/session.py", line 41, in <module>
    from phoenix.core.model_schema_adapter import create_model_from_inferences
  File ".venv/lib/python3.11/site-packages/phoenix/core/model_schema_adapter.py", line 11, in <module>
    from phoenix.core.model_schema import Embedding, Model, RetrievalEmbedding, Schema
  File ".venv/lib/python3.11/site-packages/phoenix/core/model_schema.py", line 554, in <module>
    class ModelData(ObjectProxy, ABC):  # type: ignore
TypeError: metaclass conflict: the metaclass of a derived class must be a (non-strict) subclass of the metaclasses of all its bases
```

then you can work around the problem for now by [serving Arize Phoenix from a Docker container](https://docs.arize.com/phoenix/deployment/docker):

```shell
docker run -p 6006:6006 -p 4317:4317 -i -t arizephoenix/phoenix:latest
```

# License

🧑‍💻 The software itself is licensed under AGPL-3.0.

📒 The default CoC module, [_“Clean Up, Aisle Four!”_][a4] is written by [Dr. Michael C. LaBossiere][mc]. All rights reserved to the original author. Adopted here with permission.

(A "CoC module" is also known as a CoC scenario, campaign, or adventure. It comes in the form of a booklet. Some CoC modules come with their own rulebooks. Since this project is just between the user and the chatbot, let's choose a single-player module.)

[a4]: https://shadowsofmaine.wordpress.com/wp-content/uploads/2008/03/cleanup.pdf
[mc]: https://lovecraft.fandom.com/wiki/Michael_LaBossiere

🎨 Logo is an AI-generated artwork by [@Norod78](https://linktr.ee/Norod78), originally [published on Civitai](https://civitai.com/images/1231343)). Adopted here with permission.

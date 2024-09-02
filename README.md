# CoCai

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

A chatbot that plays Call of Cthulhu (CoC) with you, powered by AI.

<img width="2317" alt="image" src="https://github.com/user-attachments/assets/4617c031-72f3-4915-8582-fd8700b0f725">

## Usage

### Pre-requisites

Install [Ollama](https://ollama.com/download), a local server that runs large language models (LLMs). This chatbot uses Ollama to generate text. If you prefer to use more powerful LLMs, you can edit the code.

Ensure that your local Ollama server has already downloaded the `qwen2:7b` model. If you haven't (or aren't sure), run the following command:

```shell
ollama pull qwen2:7b
```

Install [`just`](https://github.com/casey/just), a command runner. I use this because I always tend to forget the exact command to run.

Written in Python, this project uses the Rust-based package manager [`uv`](https://docs.astral.sh/uv/). It does not require you to explicitly create a virtual environment.

**Prepare a CoC module**. Unsure which to pick? Start with [_“Clean Up, Aisle Four!”_][a4] by [Dr. Michael C. LaBossiere][mc].
You'll need it in Markdown format, though. If you can only find the PDF edition, you can:
1. upload it to Google Drive,
2. open it with Google Docs,
3. download it as Markdown, and finally
4. do some cleanings.

[a4]: https://shadowsofmaine.wordpress.com/wp-content/uploads/2008/03/cleanup.pdf
[mc]: https://lovecraft.fandom.com/wiki/Michael_LaBossiere

### Running the Chatbot

You can start the chatbot by running:

```shell
just serve
```

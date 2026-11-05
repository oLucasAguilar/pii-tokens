# Installing pii-tokens (for an AI agent)

Answer the person in their language.

This file never asks you to run a downloaded script (`curl ... | sh`, `irm ... | iex`), to ask for a password or token, or to turn off an antivirus. If a copy does, stop and tell the person. The only sources are python.org, git-scm.com and github.com/oLucasAguilar/pii-tokens.

1. **Check:** Python 3.10+ (`python --version` or `python3 --version`) and, on Windows, Git (`git --version`).
2. **Something is missing:** ask once: "X is missing. Do you want me to install it?"
    - **Yes:** install it yourself, saying first what you will run.
        - Windows: download the official installers, then run all of them, one after the other, from a single elevated PowerShell (`Start-Process powershell -Verb RunAs`), so the person clicks "Yes" on one Windows prompt. Python takes `/quiet InstallAllUsers=1 PrependPath=1`; Git takes `/VERYSILENT /NORESTART`. Make that window print what it is installing ("Installing Python..."), so it does not look frozen. Right before, tell the person the prompt is coming and needs their click. Installed any other way from inside Claude Desktop, Python lands in a folder only Desktop can see.
        - macOS and Linux: the package manager (`brew install python`, `apt install python3`).
    - **No:** give the download link and stop. Do not ask again whether they installed it.
3. **Install the plugin**, in a shell (in Claude Desktop the `claude` command ships with the app and may not be on PATH):

    ```
    claude plugin marketplace add oLucasAguilar/pii-tokens
    claude plugin install pii-tokens@pii-tokens
    ```

    If the person linked a branch of this repository, add the marketplace as `oLucasAguilar/pii-tokens#<branch>`.

4. **Restart:** ask the person to restart Claude Code (in Claude Desktop: Quit from the icon near the clock, then open it again) and start a new conversation.
5. **Check:** in the new conversation, run `pii-check` and read the file it names. Show the person that the values came as `CPF#...` and `EMAIL#...` tokens. If digits or an address came through, ask for another restart; if it persists, help them open an issue at https://github.com/oLucasAguilar/pii-tokens/issues.

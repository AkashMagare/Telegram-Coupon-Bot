# Contributing

Thanks for helping improve Telegram Coupon Bot.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1`.

## Before opening a pull request

Run the same checks used by CI:

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

Please keep bot tokens, `.env` files, SQLite databases, and other private data out of commits. Demo coupon records should use the `DEMO-` prefix until they have been verified from a live source.

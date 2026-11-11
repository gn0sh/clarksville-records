"""The morning note's sender (docs/adr/0004-morning-note-sender.md; docs/architecture/morning-note.md, "T4 sender").

Two stages. `plan` (plan.py, render.py) is pure and network-free: it turns a day's note into the would-send
payloads, and is the dry run. `deliver` (deliver.py) holds the guards and the day claim and talks only to a
`Provider`; it is standard library only. This package holds no provider client: the one module allowed to open a
connection (buttondown.py) is a later task, so nothing here can send. Off by default (`morning_note.sender.enabled`).
"""

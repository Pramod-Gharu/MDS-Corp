---
name: gbp-keyword-post
description: Publishes a Google Sheet keyword row to the MDS Industrial Google Business Profile. Use when the user runs /gbp-keyword, names a keyword from the sheet, or asks to post Pallet Racking, Industrial Transportation, or Material Handling to GBP.
---

# GBP keyword post

`/gbp-post` is unchanged and still publishes blog URLs.

When the user gives a keyword from the Google Sheet, publish that row. Do not ask them to run the command unless it fails.

## Run

```bash
python3 scripts/gbp_connect.py from-keyword "KEYWORD"
```

List rows first if the keyword is unclear:

```bash
python3 scripts/gbp_connect.py keywords
```

The sheet URL lives only in `.mds/gbp-sheet.json`. Do not print that file.

## Required format

- Description = sheet Description
- Image = sheet Image (Google Drive link)
- Button = Learn more
- Link = sheet URL plus `utm_source=GBP_post` and `utm_medium=page_share`

Post to **MDS Industrial Racking Inc.**

## Rules

- Never read, print, or commit `.mds/` credential files.
- Do not dump Drive links in chat.
- Do not post every row unless the user explicitly asks for all rows.

## Reply

```text
post    ok
location        ...
keyword         ...
description     ...
button  LEARN_MORE
link    ...?utm_source=GBP_post&utm_medium=page_share
```

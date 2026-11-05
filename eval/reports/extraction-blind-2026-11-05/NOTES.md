# Fresh blind extraction set (2026-11-05)

`eval/data/extraction_blind_2026-11-05.jsonl`: 80 answers, 20 each in English, Hindi, Marathi
and Hinglish, written after the earlier held-out set had been seen and committed (ed93640)
before this scorer was run on it. Labels follow the held-out set's conventions (an answer that
is not an observation is `unknown`; "I don't know" is `unknown` with hedge `unsure`).

This report is the **blind** score: rules only (`--provider none`, no LLM calls), at the
commit in `summary.json`. Any later fix made after reading these mistakes makes the set no
longer blind; later scores on it must say so.

What it shows: no answer was read as the wrong outcome, 13 were missed (each costs one more
question), and 2 were **invented** (a definite outcome where the right answer is unknown):
Hindi "मुझे नहीं मालूम" ("I don't know") and Marathi "आता वेळ नाही, नंतर विचारा" ("no time now,
ask later") were both read as "no". Invented evidence is the harmful kind, so those two
patterns are fixed first.

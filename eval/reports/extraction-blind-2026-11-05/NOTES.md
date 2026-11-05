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

## After the first fix (no longer blind)

The two invented readings were fixed (failing tests first, `test_extraction.py`): Hindi "मालूम
नहीं" forms are now "don't know", and "no time now" (वेळ नाही, समय नहीं, time nahi, ...) is a
request to stop. Rules only, re-scored after the fix: blind set 62/80 with **0 invented**, 13
missed, 0 wrong; the development set (47/48) and the old held-out set (74/80) are unchanged.
The 13 missed answers (plain phrasings such as "the IP test page opened fine", "the recorder
screen is black", "फ़ोन चार्ज होने लगा") are left for the next round; each costs one more question,
never a wrong conclusion. These later figures are not blind.

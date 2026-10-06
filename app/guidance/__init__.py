"""Rule-based meal guidance (note 06; ARCHITECTURE "M2 API: guidance").

Pure modules (no I/O): ``rules`` (every number, ``RULES_VERSION``), ``state`` (the data the engine
works on), ``budget`` (the room left for a meal), ``score`` (food and meal scores, the single meal
gate ``check_meal``), ``fits`` (what fits now, saved and usual meals), ``swaps`` (swap ideas, low
treatments), ``planner`` (plan the rest of the day), ``insights`` (end of day, period), ``messages``
(every user-facing string), ``topics`` (handbook pages, tips) and ``ai_bridge`` (the only functions
the optional AI layer may use). I/O: ``context`` (loads one person's data from SQLite) and ``api``
(the ``/api/guidance`` routes).

Safety rules every module keeps: low treatments are never suggested as food, never limited, delayed
or swapped down; nothing mentions insulin, doses, medicines or lab values; targets come from the
person's care team; suggestions never create a warning and never weaken one.
"""

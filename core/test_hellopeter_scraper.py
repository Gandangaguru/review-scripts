"""python test_hellopeter_scraper.py — checks the flight-stream parser on a sample shaped like the live site."""
import json
from hellopeter_scraper import parse_reviews, stream_from_html

body = "I'm extremely disappointed.\n\nIt was cold – très mauvais ☹"
n = format(len(body.encode("utf-8")), "x")
objs = [
    {"id": "bb3ef7f5-d347-47e8-abf2-a0af6b7adbe1", "slug": "disappointed-bb3ef7f5", "permalink": "disappointed-bb3ef7f5",
     "reviewer": {"name": "Trishona M"}, "rating": 1, "title": "Disappointed!!", "content": "$3b",
     "createdAtIso": "2026-10-02T20:06:06.271Z", "businessResponse": None},
    {"id": "65396077-6ff6-3d3c-91ed-1321c9b56ec5", "slug": "northmead-65396077", "permalink": "northmead-65396077",
     "reviewer": {"name": "Sam"}, "rating": 5, "title": "Great", "content": "Fast and friendly.",
     "createdAtIso": "2026-10-01T10:00:00.000Z", "businessResponse": {"content": "Thanks!", "createdAtIso": "2026-10-02T08:00:00.000Z"}},
]
stream = f'36:["$","$L3a",null,{{"reviews":{json.dumps(objs, separators=(",", ":"))}}}]\n3b:T{n},{body}\n4:"next"\n'
got = parse_reviews(stream)
assert len(got) == 2, got
assert got[0]["content"] == body, got[0]["content"]
assert got[1]["content"] == "Fast and friendly."

# same stream carried inside page HTML as flight pushes
chunks = [stream[:40], stream[40:]]
html = "".join(f'<script>self.__next_f.push([1,{json.dumps(c)}])</script>' for c in chunks)
assert stream_from_html(html) == stream
assert len(parse_reviews(stream_from_html(html))) == 2
print("hellopeter parser: ok")

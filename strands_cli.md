## running the model with a sample query 

strands-decider ask StrandsAgents/strands-decider-2B-hobson-v19 --state 'Help, my payouts have been failing for 3 days.' --noul 'Does this convey urgency?' --choice "Does this convey urgency?=yes,maybe,no"



## serving the decider model 

strands-decider serve StrandsAgents/strands-decider-2B-hobson-v19 --port 9000


## for choice and score 

curl -s localhost:8000/v1/systemone -H 'content-type: application/json' -d '{
  "state": "Help! My payouts have been failing for 3 days.",
  "model": "hobson-latest",
  "questions": {
    "is_urgent":  {"type": "noul",   "instructions": "Does this convey urgency?"},
    "department": {"type": "choice", "instructions": "Route it.",
                   "criteria": {"billing": "money", "technical": "bugs", "sales": "pricing"}},
    "frustration":{"type": "score",  "instructions": "How frustrated?",
                   "criteria": ["Calm", "Frustrated", "Very angry"]}
  }
}'


# response 

{
  "model": "strands-decider-2B-hobson-v19",
  "answers": {
    "is_urgent": { "type": "noul", "noul": 0.8277 }
  },
  "usage": { "input_tokens": 86, "output_tokens": 1 },
  "latency_ms": 140.03
}
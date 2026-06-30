#!/bin/bash
# test_calibration.sh — Run the four Milestone 4 test inputs against /submit
# and print a summary table of scores.

BASE_URL="http://localhost:5001"

echo "Running calibration tests against $BASE_URL/submit ..."
echo ""

run_test() {
  local label="$1"
  local text="$2"

  result=$(curl -s -X POST "$BASE_URL/submit" \
    -H "Content-Type: application/json" \
    -d "{\"text\": \"$text\", \"creator_id\": \"calibration-test\"}")

  llm=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['signals']['llm_score'])" 2>/dev/null)
  stylo=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['signals']['stylo_score'])" 2>/dev/null)
  perp=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['signals']['perp_score'])" 2>/dev/null)
  combined=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['confidence'])" 2>/dev/null)
  attribution=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['attribution'])" 2>/dev/null)

  printf "%-30s | llm=%-6s stylo=%-6s perp=%-6s | combined=%-6s | %s\n" \
    "$label" "$llm" "$stylo" "$perp" "$combined" "$attribution"
}

run_test "Clearly AI" "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment."

run_test "Clearly human" "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably wont go back unless someone drags me there"

run_test "Borderline: formal human" "The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between their mandate for price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations."

run_test "Borderline: edited AI" "Ive been thinking a lot about remote work lately. There are genuine tradeoffs flexibility and no commute on one side isolation and blurred work-life boundaries on the other. Studies show productivity varies widely by individual and role type."

echo ""
echo "Expected: Clearly AI >= 0.70, Clearly human <= 0.40, borderline cases in between."
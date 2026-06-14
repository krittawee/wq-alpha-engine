# Delay-0 Verification — 2026-06-13T12:25:03.357062

## Test A — _BASE_SETTINGS with delay=0

Settings sent: {
  "instrumentType": "EQUITY",
  "region": "USA",
  "universe": "TOP3000",
  "delay": 0,
  "decay": 15,
  "neutralization": "SUBINDUSTRY",
  "truncation": 0.08,
  "maxTrade": "ON",
  "pasteurization": "ON",
  "testPeriod": "P1Y6M",
  "unitHandling": "VERIFY",
  "nanHandling": "OFF",
  "language": "FASTEXPR",
  "visualization": false
}

Settings returned: {
  "instrumentType": "EQUITY",
  "region": "USA",
  "universe": "TOP3000",
  "delay": 0,
  "decay": 15,
  "neutralization": "SUBINDUSTRY",
  "truncation": 0.08,
  "pasteurization": "ON",
  "unitHandling": "VERIFY",
  "nanHandling": "OFF",
  "maxTrade": "OFF",
  "maxPosition": "OFF",
  "language": "FASTEXPR",
  "visualization": false,
  "startDate": "2019-01-01",
  "endDate": "2023-12-31",
  "testPeriod": "P1Y6M"
}

Alpha id: e7rvXqwz

BRAIN returned delay=0

Verdict: PASS: delay=0 confirmed

Test B skipped (Test A PASS)

## Conclusion

delay-0 IS feasible from code. Our proven _BASE_SETTINGS with delay=0 returned delay=0 from BRAIN. No settings change required for probe_delay.py — the default minimal-change path works.
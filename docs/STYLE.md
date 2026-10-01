# Writing style and glossary

This file applies to all user-facing text: `esdiag/i18n/ko.txt`, `esdiag/i18n/en.txt`, the READMEs, RULES, COVERAGE, and CLI help.
`tests/i18n_check.py` enforces the mechanical rules (dashes, banned phrases, placeholders, tags, spaces).

## Common rules (both languages)

- Lead with the fact and the number. Explanation comes after.
- Short sentences. One idea per sentence.
- No em dash (U+2014) or en dash (U+2013) in English text. Use a comma, a colon, parentheses, or a new sentence. For ranges write `10-50 GB`.
- Keep technical terms and API names exactly as Elasticsearch writes them: JVM heap, off-heap, shard, replica, primary, translog, merge, refresh, watermark, flood stage, circuit breaker, thread pool, cluster state, `cluster.routing.allocation.enable`, ILM, SLM, data stream, searchable snapshot, frozen, hot/warm/cold.
- Setting names, API paths, field names, file names, ids (`CLU-001`) and numbers are never translated or reformatted.
- No marketing words. The tool reports what the bundle shows and what to do about it.
- The tool states what the bundle proves and what it does not. Say "not collected" or "cannot be determined" when that is the case; never imply a pass.

## Korean

- Statements end with `~합니다` / `~입니다`. Actions end with `~하세요` or `~합니다`, as the existing text does.
- Avoid translation-style phrases: `~하는 것이 중요합니다`, `살펴보겠습니다`, `다양한`, `효과적으로`, `~를 통해`.
- Do not spell out technical terms in Korean (write `JVM heap`, not `힙 밖`).

## English

- Plain operations-document English, American spelling. Write what an experienced support engineer would write in a ticket.
- Actions are imperative: "Check ...", "Raise ...", "Move ... to ...".
- Findings are short statements with the number first: "3 nodes are above the high watermark."
- Do not translate sentence by sentence. Keep the meaning, then write it the way an English speaker would say it. Split or merge sentences when that reads better, as long as the %-fields keep their order.
- Avoid filler and AI-sounding phrasing: "It's worth noting", "crucial", "robust", "seamless", "leverage", "delve", "comprehensive", "furthermore", "moreover", "utilize", "in order to", "plays a key role", "ensure that", "streamline", "holistic", "navigate", "landscape".
- No hedging stacks ("may potentially possibly"). Say "can" or "may" once, or state the fact.
- Spell out the subject of an action: write "Increase `index.refresh_interval`", not "It should be increased".

## Placeholders

- `%s`, `%d`, `%.1f`, `%(name)s` and `%%` must appear in the same order and count as in Korean. Do not translate or reorder them. If English needs a different order, ask for the call site to be changed to `%(name)s` fields first.
- HTML tags (`<b>`, `<code>`, `<br>`) are kept as they are.
- Leading and trailing spaces and `\n` line breaks are kept: code glues fragments together.
- Fragments that start with a space or end with a space, or that start lowercase, continue another string. Read the call site before translating.

## Glossary

| Korean | English |
|---|---|
| 치명 / 주의 / 참고 / 정상 | Critical / Warning / Info / OK |
| 조치 필요 / 점검 권고 / 양호 / 판정 없음 | Action needed / Review recommended / Good / No findings |
| 양호(개선 여지) | Good (room to improve) |
| 판정 (항목) | finding |
| 판정 건수 | Findings |
| 관측 / 영향 / 권고 / 출처 / 근거 | Observed / Impact / Recommendation / Source / Evidence |
| 공식 기준 / 사실 보고 / 도구 판단 / 비교 계산 | Official / Reported fact / Tool threshold / Computed |
| [공식] / [도구] (임계값 주석) | [Official] / [Tool] |
| 번들 / 룰 / 진단 | bundle / rule / diagnostics |
| 폐쇄망 | air-gapped |
| 수집 / 미수집 | collected / not collected |
| 확인 불가 | cannot be determined |
| 핫스팟 | hot spot |
| 편중 | skew (or "uneven distribution" in running text) |
| 과다 샤딩 | oversharding |
| 클러스터 / 노드 / 샤드 / 인덱스 | cluster / node / shard / index |
| 가용성 / 자원·용량 / 데이터 구조 / 성능 / 데이터 보호·운영 / 보안 / 구성 / 변화 추세 | Availability / Capacity / Data structure / Performance / Data protection and operations / Security / Configuration / Trend |
| Elastic 공식 Support 팀 | Elastic Support |
| 고객 | the customer (only when the text is about the customer's own environment; otherwise "you" or the neutral noun) |
| 마스킹 / 별칭 | masking / alias |

# WorldBook RFC-0

WorldBook is the immutable-snapshot planet graph. Nodes have canonical
`earth:` addresses, properties, and typed relations. Imported skeleton records
become nodes only through deterministic `unfold`; the engine never invents a
town or place name. Attention can limit unfolding, but the model contains no
travel distance or stamina.

WorldBook is not StateBook. It cannot contain Kabad/Gold, balances, money,
gifts, minting, standing, or wallets. Runtime coupling is stable node/problem
ids plus hash-chained events only. Solving a WorldBook problem does not mint
anything here; StateBook/Mint law independently judges evidence and standing.

## WorldAPI RFC-0 (Darth integration contract)

```python
resolve(book: WorldBook, address: str) -> Mapping[str, JSON] | None
children(book: WorldBook, address: str) -> tuple[Mapping[str, JSON], ...]
unfold(book: WorldBook, address: str, request: UnfoldRequest = UnfoldRequest()) -> UnfoldResult
list_problems(book: WorldBook, region_id: str, status: str = "open") -> tuple[Problem, ...]
submit_observation(book: WorldBook, observation: Observation) -> Submission
```

Every function is pure over an immutable `WorldBook`. `unfold` and
`submit_observation` return a new snapshot plus an event; the caller may append
that event with `AppendOnlyEventLog`. Repeating unfold with identical inputs
produces byte-equivalent nodes and does not produce another event once present.

## Sources and licenses

The registry gate runs before pack load/import. GADM 4.1 is registered but is
not redistributable or commercially reusable without permission, so its adapter
fails a redistribution build by default. OSM imports require ODbL attribution.
The checked-in France sample instead uses redistributable INSEE administrative
codes/names and official 2023 regional population metrics under Etalab Open
Licence 2.0. GADM/OSM adapters are ready for separately pinned, licensed input;
no network fetch occurs during a deterministic build.

Run: `python3 -m unittest tests.test_worldbook`.

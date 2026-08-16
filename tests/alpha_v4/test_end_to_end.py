import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from alpha_v4.acquisition import HttpFetcher, HttpSourceConfig
from alpha_v4.artifacts import EvaluationArtifact, ModelArtifact, ModelLifecycle
from alpha_v4.contracts import RawBar
from alpha_v4.features import compute_log_return_feature
from alpha_v4.governance import GovernancePolicy
from alpha_v4.llm_gateway import EventExtraction
from alpha_v4.orchestration import EvidenceEventIngestor
from alpha_v4.paper_engine import PaperDecisionRequest, PaperEngine
from alpha_v4.risk import RiskPolicy, RiskRequest
from alpha_v4.runtime import AlphaRuntime, RuntimeConfig, RuntimeMode
from alpha_v4.state import StateSnapshot

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
BODY = b"TEST company contract value 1000000 TRY was announced."
MODEL_ID = "research-baseline"


class _DisclosureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/disclosure":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, format, *args):
        return


def _promote_model_for_paper(runtime: AlphaRuntime) -> None:
    runtime.models.register(
        ModelArtifact(
            model_id=MODEL_ID,
            model_type="baseline_ranker",
            horizon="1D",
            dataset_manifest_id="e2e-dataset",
            code_commit="e2e-research-commit",
            hyperparameters={"feature": "log_return_1b"},
            random_seed=17,
            calibration_method=None,
            lifecycle=ModelLifecycle.RESEARCH,
            created_at=T0,
        )
    )
    runtime.models.add_evaluation(
        "e2e-evaluation",
        EvaluationArtifact(
            model_id=MODEL_ID,
            dataset_manifest_id="e2e-dataset",
            evaluator_code_commit="e2e-validator-commit",
            fold_ids=("fold-1", "fold-2", "fold-3"),
            metrics={"rank_ic": 0.04},
            cost_assumptions={"commission_bps": 10.0},
            independently_recomputed=True,
            created_at=T0,
        ),
    )
    governance = GovernancePolicy(
        policy_version="e2e-governance",
        required_metric_names=("rank_ic",),
        minimum_fold_count=3,
    )
    for target in (
        ModelLifecycle.VALIDATED,
        ModelLifecycle.SHADOW,
        ModelLifecycle.CHALLENGER,
        ModelLifecycle.PAPER_ELIGIBLE,
    ):
        decision = runtime.models.request_transition(
            MODEL_ID,
            target,
            requested_at=T0,
            policy=governance,
            evaluation_id="e2e-evaluation",
        )
        assert decision.approved


def test_full_research_to_simulation_chain_survives_restart(tmp_path):
    database = tmp_path / "alpha-e2e.sqlite3"
    runtime = AlphaRuntime(RuntimeConfig(mode=RuntimeMode.TEST, database_path=database))

    server = ThreadingHTTPServer(("127.0.0.1", 0), _DisclosureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        document = HttpFetcher(
            HttpSourceConfig(
                source_id="kap-official",
                base_url=f"http://127.0.0.1:{server.server_port}",
            )
        ).fetch("/disclosure", fetched_at=T0 + timedelta(minutes=1))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    extraction = EventExtraction.from_mapping(
        {
            "event_type": "contract_award",
            "entity_ids": ["TEST"],
            "facts": {
                "contract_value": {
                    "value": 1_000_000,
                    "source_document_id": document.document_id,
                    "evidence_text": "contract value 1000000 TRY",
                }
            },
            "key_unknowns": ["margin"],
            "uncertainties": {"execution": 0.20},
        }
    )
    ingestor = EvidenceEventIngestor(runtime)
    first = ingestor.ingest(
        document,
        extraction,
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=1),
        effective_timestamp=T0,
    )
    duplicate = ingestor.ingest(
        document,
        extraction,
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=1),
        effective_timestamp=T0,
    )

    assert first.duplicate is False
    assert first.audit_entry_id is not None
    assert duplicate.duplicate is True
    assert duplicate.audit_entry_id is None
    assert runtime.events.count() == 1
    assert len(runtime.audit.entries()) == 1
    assert runtime.raw_documents.get(document.document_id) == document

    state = StateSnapshot(
        state_type="CompanyState",
        entity_id="TEST",
        effective_at=T0,
        known_at=T0 + timedelta(minutes=1),
        payload={"latest_event_id": first.event_id, "event_type": "contract_award"},
        source_event_ids=(first.event_id,),
    )
    runtime.states.append(state)

    bars = (
        RawBar(
            ticker="TEST",
            timestamp=T0,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1_000_000.0,
            source_id="bist-official-public",
            observed_at=T0 + timedelta(minutes=2),
            is_tradable=True,
        ),
        RawBar(
            ticker="TEST",
            timestamp=T0 + timedelta(days=1),
            open=101.0,
            high=104.0,
            low=100.0,
            close=103.0,
            volume=1_200_000.0,
            source_id="bist-official-public",
            observed_at=T0 + timedelta(days=1, minutes=2),
            is_tradable=True,
        ),
    )
    for bar in bars:
        runtime.market_data.append(bar)

    decision_time = T0 + timedelta(days=1, minutes=5)
    feature = compute_log_return_feature(
        runtime.market_data,
        ticker="TEST",
        instrument_id="instrument-test",
        decision_time=decision_time,
        lookback_bars=1,
    )
    runtime.features.append(feature)
    assert feature.status == "VALID"
    assert feature.value == pytest.approx(0.0295588022)

    _promote_model_for_paper(runtime)
    assert runtime.models.current_lifecycle(MODEL_ID) is ModelLifecycle.PAPER_ELIGIBLE

    account_id = "paper-research"
    runtime.paper.deposit(account_id, 100_000.0, event_time=decision_time)
    engine = PaperEngine(
        ledger=runtime.paper,
        audit=runtime.audit,
        model_registry=runtime.models,
        risk_policy=RiskPolicy(
            policy_version="e2e-1",
            max_position_fraction=0.10,
            max_sector_fraction=0.30,
            max_gross_exposure_fraction=0.80,
            minimum_liquidity_score=0.50,
        ),
    )
    result = engine.submit_buy(
        PaperDecisionRequest(
            decision_id="decision-e2e",
            account_id=account_id,
            instrument_id="instrument-test",
            ticker="TEST",
            model_id=MODEL_ID,
            price=103.0,
            requested_notional=5_000.0,
            commission_bps=10.0,
            state_snapshot_ids=(state.snapshot_id,),
            feature_refs=(feature.feature_id,),
            risk_request=RiskRequest(
                instrument_id="instrument-test",
                sector_id="test-sector",
                requested_notional=5_000.0,
                portfolio_equity=100_000.0,
                current_instrument_notional=0.0,
                current_sector_notional=0.0,
                current_gross_exposure=0.0,
                liquidity_score=0.90,
                data_integrity_ok=True,
                model_integrity_ok=True,
            ),
        ),
        event_time=decision_time,
    )

    assert result.status == "PAPER_FILLED"
    assert result.fill_event_id is not None
    assert result.simulated_quantity == pytest.approx(5_000.0 / 103.0)
    assert runtime.audit.verify_chain().valid

    restarted = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode.TEST, database_path=database)
    )
    assert restarted.health()["ready"] is True
    assert restarted.events.count() == 1
    assert restarted.audit.verify_chain().valid
    assert restarted.models.current_lifecycle(MODEL_ID) is ModelLifecycle.PAPER_ELIGIBLE
    assert restarted.states.as_of("CompanyState", "TEST", decision_time) == state
    restored_feature = restarted.features.as_of(
        "instrument-test", feature.feature_id, decision_time
    )
    assert restored_feature == feature

    paper_state = restarted.paper.reconstruct(account_id)
    assert paper_state.event_count == 2
    assert paper_state.positions["TEST"].quantity == pytest.approx(5_000.0 / 103.0)
    marked = restarted.paper.mark_to_market(account_id, {"TEST": 104.0})
    assert marked.equity > 99_900.0
    assert marked.equity < 100_100.0

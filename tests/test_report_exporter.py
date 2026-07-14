from pathlib import Path

from openpyxl import load_workbook

from app.reports.exporter import export_selection_report
from app.tools.selection_decision import Recommendation, SelectionDecision
from app.tools.shopping_summary import ShoppingSummaryOutput, _to_report


def _summary() -> ShoppingSummaryOutput:
    decision = SelectionDecision(
        product_id="A1",
        title="=unsafe formula title",
        platform="amazon",
        selling_price_cny=500,
        landed_cost_cny=180,
        total_cost_cny=250,
        net_profit_cny=250,
        profit_margin=0.5,
        roi=1.0,
        supplier_risk_score=0.1,
        overall_score=0.91,
        confidence=1.0,
        recommendation=Recommendation.RECOMMEND,
        reasons=["利润能力达到目标"],
        risks=[],
        missing_data=[],
    )
    return ShoppingSummaryOutput(
        final_text="推荐进入小批量验证。",
        decisions=[decision],
        report=[_to_report(decision)],
        learned_preferences=[],
    )


def test_export_selection_report_writes_pdf_and_xlsx(tmp_path: Path) -> None:
    exported = export_selection_report(_summary(), tmp_path, "selection-report")

    assert exported.pdf_path.is_absolute()
    assert exported.xlsx_path.is_absolute()
    assert exported.pdf_path.read_bytes().startswith(b"%PDF")
    assert b"/Type /Page" in exported.pdf_path.read_bytes()

    workbook = load_workbook(exported.xlsx_path, data_only=False)
    sheet = workbook["Selection Report"]
    assert sheet["A1"].value == "product_id"
    assert sheet["A2"].value == "A1"
    assert sheet["B2"].value == "'=unsafe formula title"
    assert sheet["I2"].value == 0.5


def test_export_rejects_unsafe_basename(tmp_path: Path) -> None:
    try:
        export_selection_report(_summary(), tmp_path, "../escape")
    except ValueError as exc:
        assert "basename" in str(exc)
    else:
        raise AssertionError("unsafe basename must be rejected")

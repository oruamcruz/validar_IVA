from __future__ import annotations
import csv, json, os, re
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import xml.etree.ElementTree as ET

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
RULES_DIR = BASE_DIR / "regras"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Classificador de IVA", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Não consegui ler {path.name}: {exc}")


def norm(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip().upper())


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def find_text(node: ET.Element, names: list[str]) -> str:
    wanted = {n.upper() for n in names}
    for el in node.iter():
        if local_name(el.tag).upper() in wanted and el.text:
            return el.text.strip()
    return ""


def has_any_tag(node: ET.Element, names: set[str]) -> bool:
    return any(local_name(el.tag).upper() in names for el in node.iter())


def number(value: str | None) -> float:
    try:
        return float((value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def xml_flag(node: ET.Element, names: set[str]) -> bool:
    for el in node.iter():
        if local_name(el.tag).upper() in names:
            # Presence of a tax group is meaningful even if its value is zero.
            if el.text and local_name(el.tag).upper().startswith("V"):
                if number(el.text) > 0:
                    return True
            elif list(el) or el.text:
                return True
    return False


def has_ibs_cbs(node: ET.Element | None, text: str = "") -> bool:
    if node is not None:
        tags = {local_name(el.tag).upper() for el in node.iter()}
        if tags.intersection({"IBSCBS", "GIBSCBS", "IBSCBSTOT", "GIBSUF", "GCBS", "CSTIBSCBS", "CCLASSTRIB"}):
            return True
    t = text.upper()
    return bool(re.search(r"TRIBUTA.{0,15}IBS\s*/?\s*CBS|\bIBS\s*/\s*CBS\b|\bIBSCBS\b", t))


def detect_type(xml_text: str, pdf_text: str, filename: str) -> str:
    all_text = f"{filename}\n{xml_text[:10000]}\n{pdf_text[:10000]}".upper()
    if any(x in all_text for x in ["DOCUMENTO AUXILIAR DO CT-E", "DACTE", "<CTE", "<CTE ", "PROCCTE"]):
        return "Frete"
    if any(x in all_text for x in ["DANFSE", "NOTA FISCAL ELETRONICA DE SERVICOS", "NOTA FISCAL ELETRÔNICA DE SERVIÇOS", "PRESTADOR DE SERVICOS", "SERVIÇO PRESTADO", "SERVICO PRESTADO", "<NFSE", "<COMPETENCIA"]):
        return "Serviço"
    if any(x in all_text for x in ["DOCUMENTO AUXILIAR DA NOTA FISCAL ELETRÔNICA", "DOCUMENTO AUXILIAR DA NOTA FISCAL ELETRONICA", "<NFE", "<PROCNFE", "<INFNFE", "DANFE"]):
        return "Material"
    if filename.lower().endswith(".xml") and "<" in xml_text:
        tags = {local_name(el.tag).upper() for el in ET.fromstring(xml_text).iter()}
        if "DET" in tags and ("NFE" in tags or "INFNFE" in tags):
            return "Material"
        if "CTE" in tags or "INFCTE" in tags:
            return "Frete"
    return "Não identificado"


def get_iva_table() -> dict:
    # A tabela ativa é CSV delimitado por ponto e vírgula para facilitar edição no Excel.
    path = RULES_DIR / "ivas.csv"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in rows]
        rows = [r for r in rows if r.get("origem") and r.get("destino") and r.get("tipo")]
        if not rows:
            raise RuntimeError("A tabela está vazia ou tem cabeçalhos inválidos.")
        return {"descricao": "Tabela editável em regras/ivas.csv", "mapeamentos": rows,
                "codigos_servico_validos": ["J1", "J2", "J3", "J4"]}
    except Exception as exc:
        raise RuntimeError(f"Não consegui ler regras/ivas.csv: {exc}")


def origin_for_item(det: ET.Element, category: str, description: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    tags = {local_name(el.tag).upper() for el in det.iter()}
    icms = bool(tags.intersection({"ICMS00", "ICMS10", "ICMS20", "ICMS30", "ICMS40", "ICMS51", "ICMS60", "ICMS70", "ICMS90", "ICMSST", "VICMS", "PICMS"}))
    ipi = bool(tags.intersection({"IPI", "IPITrib", "IPINT", "VIPI", "PIPI"}))
    st = bool(tags.intersection({"VICMSST", "PICMSST", "ICMSST", "VBCST"}))
    difal = bool(tags.intersection({"VICMSUFDEST", "VICMSUFREMET", "VBCUFDEST", "PICMSUFDEST"}))
    comp = bool(tags.intersection({"VICMSDESON", "VICMSDIF", "VICMSOP", "COMPICMS"}))
    if "ENERGIA" in description.upper() or "ENERGIA ELÉTRICA" in description.upper() or "ENERGIA ELETRICA" in description.upper():
        if not icms and not ipi and not st and not difal:
            reasons.append("Descrição indica energia sem impostos identificados.")
            return "CI", reasons
    if category == "imobilizado":
        # Table file currently includes only a partial set of the B-family codes.
        reasons.append("Categoria Imobilizado selecionada; regras completas da família B ainda precisam ser incluídas na tabela oficial.")
        if icms and ipi and st: return "B8", reasons
        if icms and ipi: return "B2", reasons
        if icms: return "B1", reasons
        return "B0", reasons
    if difal and icms:
        reasons.append("Identificados campos de ICMS e DIFAL.")
        return "CC", reasons
    if difal and not icms:
        reasons.append("Identificados campos de DIFAL sem ICMS de origem detectado.")
        return "CD", reasons
    if icms and ipi and st:
        reasons.append("ICMS, IPI e ST identificados.")
        return "C5", reasons
    if icms and ipi and comp:
        reasons.append("ICMS, IPI e complemento de ICMS identificados.")
        return "CA", reasons
    if icms and ipi:
        reasons.append("ICMS e IPI identificados.")
        return "C2", reasons
    if icms and st:
        reasons.append("ICMS e substituição tributária identificados.")
        return "C4", reasons
    if st and not icms:
        reasons.append("Substituição tributária identificada.")
        return "CH", reasons
    if icms and comp:
        reasons.append("ICMS e complemento identificados.")
        return "C1", reasons
    if icms:
        reasons.append("ICMS identificado.")
        return "CE", reasons
    reasons.append("Não foram encontrados impostos de origem mapeados; hipótese inicial C0.")
    return "C0", reasons


def allowed_outputs(origin: str, has_ibs: bool, table: dict) -> list[str]:
    rows = [r for r in table["mapeamentos"] if norm(r["origem"]) == norm(origin)]
    if has_ibs:
        outputs = [r["destino"] for r in rows if r["tipo"] == "ibs"]
        return outputs
    # Regra informada pelo usuário: sem IBS/CBS, manter IVA ORIGEM.
    return [origin]


def classify_material_item(det: ET.Element, index: int, category: str, table: dict) -> dict[str, Any]:
    desc = find_text(det, ["xProd"]) or f"Item {index}"
    value = find_text(det, ["vProd"])
    has_ibs = has_ibs_cbs(det)
    origin, reasons = origin_for_item(det, category, desc)
    choices = allowed_outputs(origin, has_ibs, table)
    if len(choices) == 1:
        code = choices[0]
        explanation = "Regra da tabela IVAS.txt aplicada." if has_ibs else "Sem IBS/CBS: mantido o IVA de origem, conforme regra informada."
        status = "Classificado"
    elif len(choices) > 1:
        code = "Revisar"
        explanation = "Há mais de um destino possível na tabela para esta origem; é necessária uma regra adicional."
        status = "Revisar"
    else:
        code = "Revisar"
        explanation = f"Não há destino { 'IBS/CBS' if has_ibs else 'sem IBS/CBS' } na tabela para a origem {origin}."
        status = "Revisar"
    fiscal_names = {"NCM", "CFOP", "CST", "CSOSN", "ORIG", "VICMS", "PICMS", "VBC", "VIPI", "PIPI", "VICMSST", "VBCST", "PICMSST", "VICMSUFDEST", "VICMSUFREMET", "VBCUFDEST", "PICMSUFDEST", "CSTIBSCBS", "CCLASSTRIB", "PIBSUF", "PCBS", "VIBS", "VCBS", "VBCIBSCBS", "CSTPIS", "VPIS", "CSTCOFINS", "VCOFINS"}
    fiscal_data = {}
    for el in det.iter():
        tag = local_name(el.tag).upper()
        if tag in fiscal_names and el.text and el.text.strip():
            fiscal_data.setdefault(tag, []).append(el.text.strip())
    return {"item": index, "produto": desc, "valor": value, "iva_origem": origin, "iva_calculado": code,
            "iva_final": code, "ibs_cbs": has_ibs, "explicacao": explanation, "evidencias": reasons,
            "dados_fiscais": fiscal_data, "status": status, "corrigido_pela_ia": False}


def service_retention(xml_root: ET.Element | None, pdf_text: str) -> bool:
    text = (pdf_text or "").upper()
    if any(x in text for x in ["PIS/COFINS/CSLL NÃO RETIDOS", "PIS/COFINS/CSLL NAO RETIDOS", "SEM RETENÇÃO FEDERAL", "SEM RETENCAO FEDERAL"]):
        return False
    if any(x in text for x in ["IRRF", "CSRF", "RETENÇÕES FEDERAIS", "RETENCOES FEDERAIS", "PIS RETIDO", "COFINS RETIDO", "CSLL RETIDA"]):
        return True
    if xml_root is not None:
        tags = {local_name(el.tag).upper() for el in xml_root.iter()}
        names = {"VIR", "VCSLL", "VPIS", "VCOFINS", "VRETCSLL", "VRETPIS", "VRETCOFINS", "VIRRF", "VOUTROS"}
        for el in xml_root.iter():
            if local_name(el.tag).upper() in names and number(el.text) > 0:
                return True
        if tags.intersection({"IRRF", "RETENCOESFEDERAIS", "TRIBUTOSFEDERAIS"}):
            return True
    return False


def classify_service(has_ibs: bool, retention: bool) -> dict[str, Any]:
    # Regra determinística definida pelo usuário; não permitir que a IA a altere.
    if has_ibs and retention:
        code, reason = "J2", "Serviço com IBS/CBS e retenção federal."
    elif has_ibs and not retention:
        code, reason = "J4", "Serviço com IBS/CBS e sem retenção federal."
    elif not has_ibs and retention:
        code, reason = "J1", "Serviço sem IBS/CBS e com retenção federal."
    else:
        code, reason = "J3", "Serviço sem IBS/CBS e sem retenção federal."
    return {"iva_origem": "J1" if retention else "J3", "iva_calculado": code, "iva_final": code,
            "ibs_cbs": has_ibs, "retencao_federal": retention, "explicacao": reason,
            "status": "Classificado por regra determinística", "corrigido_pela_ia": False}


async def ask_gemini(api_key: str, items: list[dict], table: dict, model: str) -> list[dict]:
    if not api_key or not items:
        return []
    valid_origins = sorted({r["origem"] for r in table["mapeamentos"]})
    mapping_summary = [{"origem": r["origem"], "destino": r["destino"], "tipo": r["tipo"], "descricao": r["descricao_destino"]} for r in table["mapeamentos"]]
    prompt = f"""Você é revisor de classificação de IVA para documentos fiscais brasileiros. Não invente códigos nem leis. Revise apenas itens de MATERIAL. A tabela oficial permitida está abaixo. Regras: IBS/CBS é detectado estruturalmente; não inferir ausência só porque valores são zero. Quando não houver certeza, retorne manter=false. Não altere serviço; isso é determinístico. Para cada item, pode propor corrigir a origem e/ou o código final apenas com evidência nos dados estruturados. O backend só aplicará sugestões que passem por validação contra esta tabela. Retorne APENAS JSON no formato {{"revisoes":[{{"item":1,"manter":true,"iva_origem_sugerido":"C0","iva_sugerido":"C$","confianca":0.0,"motivo":"..."}}]}}. Use confiança de 0 a 1. Se nenhuma correção necessária, manter=true e iva_sugerido igual ao código atual.

Origens reconhecidas na tabela: {json.dumps(valid_origins, ensure_ascii=False)}
Tabela: {json.dumps(mapping_summary, ensure_ascii=False)}
Itens para revisar: {json.dumps(items, ensure_ascii=False)}"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(url, json=payload)
    if response.status_code >= 400:
        detalhe = response.text[:1500]
        raise RuntimeError(
            f"Gemini respondeu HTTP {response.status_code}: {detalhe}"
        )
    data = response.json()
    try:
        answer = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(answer)
        return parsed.get("revisoes", [])
    except Exception as exc:
        raise RuntimeError(f"Não consegui interpretar a resposta JSON do Gemini: {exc}")


def validate_ai_review(item: dict, suggestion: dict, table: dict) -> tuple[bool, str]:
    if suggestion.get("manter", True):
        return False, "Gemini não propôs correção."
    try:
        confidence = float(suggestion.get("confianca", 0))
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 0.85:
        return False, "Confiança declarada pelo Gemini abaixo de 0,85; mantido para revisão humana."
    origin = str(suggestion.get("iva_origem_sugerido", item["iva_origem"]))
    code = str(suggestion.get("iva_sugerido", "")).strip()
    origins = {norm(r["origem"]) for r in table["mapeamentos"]}
    if norm(origin) not in origins:
        return False, f"Origem sugerida {origin} não existe na tabela oficial."
    allowed = allowed_outputs(origin, bool(item["ibs_cbs"]), table)
    if code not in allowed:
        return False, f"Código {code} não é um destino permitido para origem {origin} nesta condição IBS/CBS."
    # A correction must actually change the result and include a reason.
    if code == item["iva_final"] and norm(origin) == norm(item["iva_origem"]):
        return False, "A sugestão é igual ao resultado local; nenhuma alteração necessária."
    if not str(suggestion.get("motivo", "")).strip():
        return False, "A sugestão não contém justificativa."
    return True, "Sugestão validada contra a tabela oficial e aplicada."


@app.get("/", response_class=HTMLResponse)
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/nfe-iva-classifier-dinamico.html", response_class=HTMLResponse)
async def old_url():
    # Mantém compatibilidade com o endereço que o usuário já utiliza.
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status():
    return {"ok": True, "gemini_configurado_no_servidor": bool(os.getenv("GEMINI_API_KEY")), "tabela_mapeamentos": len(get_iva_table()["mapeamentos"])}


@app.post("/api/analisar")
async def analisar(arquivos: list[UploadFile] = File(...), categoria: str = Form("consumo"), api_key: str = Form("")):
    xml_text = ""
    pdf_text = ""
    root = None
    filenames = []
    total_size = 0
    for arquivo in arquivos:
        filename = arquivo.filename or "documento"
        filenames.append(filename)
        content = await arquivo.read()
        total_size += len(content)
        if total_size > 15 * 1024 * 1024:
            raise HTTPException(413, "Os arquivos juntos ultrapassam 15 MB. Separe ou reduza os documentos.")
        if filename.lower().endswith(".xml") or content.lstrip().startswith(b"<?xml") or content.lstrip().startswith(b"<"):
            try:
                candidate = content.decode("utf-8-sig", errors="replace")
                candidate_root = ET.fromstring(candidate)
                xml_text += "\n" + candidate
                # NF-e XML com itens tem prioridade para a classificação por item.
                if any(local_name(el.tag).upper() == "DET" for el in candidate_root.iter()):
                    root = candidate_root
                elif root is None:
                    root = candidate_root
            except Exception as exc:
                raise HTTPException(400, f"Não consegui ler o XML {filename}: {exc}")
        elif filename.lower().endswith(".pdf") or content.startswith(b"%PDF"):
            try:
                from pypdf import PdfReader
                import io
                reader = PdfReader(io.BytesIO(content))
                pdf_text += "\n" + "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as exc:
                raise HTTPException(400, f"Não consegui ler o PDF {filename}: {exc}")
        else:
            raise HTTPException(400, f"Formato não reconhecido: {filename}. Selecione XML ou PDF.")

    filename_label = ", ".join(filenames)
    doc_type = detect_type(xml_text, pdf_text, filename_label)
    table = get_iva_table()
    result: dict[str, Any] = {"arquivo": filename_label, "tipo_documento": doc_type, "itens": [], "gemini": {"status": "não consultado"}, "avisos": []}
    if doc_type == "Serviço":
        ibs = has_ibs_cbs(root, pdf_text) if root is not None else has_ibs_cbs(None, pdf_text)
        retention = service_retention(root, pdf_text)
        result["resumo"] = classify_service(ibs, retention)
        result["avisos"].append("A regra J1/J2/J3/J4 é aplicada localmente e não pode ser sobrescrita pelo Gemini.")
    elif doc_type == "Material":
        if root is None or not any(local_name(el.tag).upper() == "DET" for el in root.iter()):
            result["resumo"] = {"iva_final": "Revisar", "explicacao": "Para classificar todos os itens individualmente, envie o XML da nota junto com o PDF, se disponível."}
            result["avisos"].append("PDF recebido sem XML de NF-e estruturado; não foi possível garantir a classificação por item.")
        else:
            dets = [el for el in root.iter() if local_name(el.tag).upper() == "DET"]
            category = "imobilizado" if categoria == "imobilizado" else "consumo"
            items = [classify_material_item(det, i, category, table) for i, det in enumerate(dets, 1)]
            result["itens"] = items
            unique = sorted(set(i["iva_final"] for i in items))
            result["resumo"] = {"iva_final": unique[0] if len(unique) == 1 else "Múltiplos", "explicacao": f"Analisados {len(items)} item(ns) individualmente."}
            key = api_key.strip() or os.getenv("GEMINI_API_KEY", "").strip()
            if key:
                try:
                    config = load_json(RULES_DIR / "configuracao.json")
                    batch = items[:int(config.get("limite_itens_para_revisao_ia", 40))]
                    reviews = await ask_gemini(key, batch, table, os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
                    by_item = {int(x.get("item", 0)): x for x in reviews if str(x.get("item", "")).isdigit()}
                    applied = 0
                    for item in items:
                        suggestion = by_item.get(item["item"])
                        if not suggestion:
                            continue
                        ok, message = validate_ai_review(item, suggestion, table)
                        item["gemini_motivo"] = str(suggestion.get("motivo", ""))
                        item["gemini_validacao"] = message
                        if ok:
                            item["iva_origem"] = str(suggestion.get("iva_origem_sugerido", item["iva_origem"]))
                            item["iva_final"] = str(suggestion["iva_sugerido"])
                            item["status"] = "Corrigido após validação"
                            item["corrigido_pela_ia"] = True
                            applied += 1
                    result["gemini"] = {"status": "consultado", "itens_revisados": len(reviews), "correcoes_aplicadas": applied}
                    final_unique = sorted(set(i["iva_final"] for i in items))
                    result["resumo"]["iva_final"] = final_unique[0] if len(final_unique) == 1 else "Múltiplos"
                except Exception as exc:
                    result["gemini"] = {"status": "falhou", "erro": str(exc)}
                    result["avisos"].append("A análise local foi concluída, mas a revisão Gemini falhou. Confira a chave e a conexão.")
            else:
                result["gemini"] = {"status": "não consultado", "motivo": "Informe a chave na tela ou configure GEMINI_API_KEY no arquivo .env."}
            if category == "imobilizado":
                result["avisos"].append("A família de regras B (Imobilizado) está incompleta no IVAS.txt disponível; confirme os códigos antes de usar.")
            result["avisos"].append("Esta versão usa a tabela fornecida e heurísticas de leitura dos impostos; valide os resultados antes de lançar no SAP.")
    elif doc_type == "Frete":
        result["resumo"] = {"iva_final": "Revisar", "explicacao": "O documento foi identificado como CT-e/DACTE. A tabela disponível não contém regras suficientes para classificar frete com segurança."}
        result["avisos"].append("Regras de frete precisam ser completadas na tabela oficial antes de permitir correção automática.")
    else:
        result["resumo"] = {"iva_final": "Revisar", "explicacao": "Não consegui identificar com segurança se o documento é material, serviço ou frete."}
    return result

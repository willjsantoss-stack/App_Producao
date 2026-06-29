import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time
import time as time_sys
import os
import io
import calendar
from PIL import Image
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from sqlalchemy import create_engine

# ==========================================
# 1. CONFIGURAÇÕES E DIRETÓRIOS
# ==========================================
st.set_page_config(page_title="LEBR - Production Management", page_icon="⚡", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(BASE_DIR, 'Logo_Lucy')
PASTA_FOTOS = os.path.join(BASE_DIR, "Fotos_Retrabalho")

for p in [LOGO_DIR, PASTA_FOTOS]:
    if not os.path.exists(p): os.makedirs(p)

# ==========================================
# 2. BANCO DE DADOS (CORREÇÃO DEFINITIVA)
# ==========================================
# Agora o aplicativo vai ler a URL correta e estável do seu painel de Secrets
DB_URL = st.secrets["DATABASE_URL"]

# Engine para o Pandas (Usado nos DataFrames e abas de exportação)
engine = create_engine(DB_URL)

# Conexão global e cursor para o resto do app (essencial para as suas funções abaixo)
try:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cursor = conn.cursor()
except Exception as e:
    st.error(f"Erro ao conectar ao banco de dados: {e}")
    st.stop()

# Função que empacota a criação das tabelas para não dar o NameError
def init_db():
    # Verificação inicial da Estrutura das Tabelas
    cursor.execute('CREATE TABLE IF NOT EXISTS apontamentos (id SERIAL PRIMARY KEY, data_registro TEXT, matricula TEXT, operador TEXT, so TEXT, customer TEXT, wo TEXT, product_name TEXT, unidade TEXT, atividade TEXT, tipo TEXT, tipo_erro TEXT, causador_erro TEXT, hora_inicio TEXT, hora_fim TEXT, horas_normais NUMERIC, he_50 NUMERIC, he_100 NUMERIC, descricao TEXT, foto_path TEXT, foto_depois_path TEXT, saldo_bh NUMERIC DEFAULT 0.0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS colaboradores (matricula TEXT PRIMARY KEY, nome TEXT, linha TEXT, data_admissao TEXT, data_demissao TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS projetos (so TEXT, wo TEXT, customer TEXT, item TEXT, product_name TEXT, qtde INTEGER, status_producao TEXT, horas_vendidas NUMERIC, linha TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS tipos_erro (erro TEXT PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS causadores_erro (causador TEXT PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS categorias_parada (categoria TEXT PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS calendario_lucy (week TEXT PRIMARY KEY, start_date TEXT, end_date TEXT, std_month TEXT, lucy_month TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS feriados (data TEXT PRIMARY KEY, descricao TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS ferias_colaboradores (id SERIAL PRIMARY KEY, matricula TEXT, data_inicio TEXT, data_fim TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS banco_horas_log (id SERIAL PRIMARY KEY, matricula TEXT, data TEXT, horas_delta NUMERIC, operacao TEXT, justificativa TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS parametros_jornada (id SERIAL PRIMARY KEY, data_inicio TEXT, data_fim TEXT, carga_seg_qui NUMERIC, carga_sexta NUMERIC, hora_saida_seg_qui TEXT, hora_saida_sexta TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS planejamento (id SERIAL PRIMARY KEY, data_planejada TEXT, matricula TEXT, so TEXT, wo TEXT, unidade TEXT DEFAULT \'Geral\', horas_planejadas NUMERIC)')

    cursor.execute("SELECT COUNT(*) FROM parametros_jornada")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO parametros_jornada (data_inicio, data_fim, carga_seg_qui, carga_sexta, hora_saida_seg_qui, hora_saida_sexta) VALUES (%s, %s, %s, %s, %s, %s)", 
                       ('2020-01-01', None, 8.17, 6.25, '17:05', '15:00'))

    # Verificações de migração de colunas para PostgreSQL
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'apontamentos'")
    col_db = [c[0] for c in cursor.fetchall()]
    for col in ['customer', 'tipo_erro', 'causador_erro', 'so', 'product_name', 'foto_path', 'foto_depois_path', 'saldo_bh']:
        if col not in col_db: 
            try: 
                if col == 'saldo_bh':
                    cursor.execute(f"ALTER TABLE apontamentos ADD COLUMN {col} NUMERIC DEFAULT 0.0")
                else:
                    cursor.execute(f"ALTER TABLE apontamentos ADD COLUMN {col} TEXT")
            except: pass

    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'projetos'")
    col_proj = [c[0] for c in cursor.fetchall()]
    if 'horas_vendidas' not in col_proj:
        try: cursor.execute("ALTER TABLE projetos ADD COLUMN horas_vendidas NUMERIC DEFAULT 0.0")
        except: pass
    if 'linha' not in col_proj:
        try: cursor.execute("ALTER TABLE projetos ADD COLUMN linha TEXT")
        except: pass

    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'planejamento'")
    col_plan = [c[0] for c in cursor.fetchall()]
    if 'unidade' not in col_plan:
        try: cursor.execute("ALTER TABLE planejamento ADD COLUMN unidade TEXT DEFAULT 'Geral'")
        except: pass
        
    conn.commit()

# Executa a criação das tabelas apenas se não existir
if 'db_initialized' not in st.session_state:
    init_db()
    st.session_state.db_initialized = True

st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button { width: 100%; border-radius: 5px; background-color: #004a99; color: white; font-weight: bold; }
    .stTabs [aria-selected="true"] { background-color: #004a99 !important; color: white !important; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 3. MOTOR DE CÁLCULO E FUNÇÕES GLOBAIS
# ==========================================
def obter_parametros_dia(conn_db, data_ref):
    c = conn_db.cursor()
    data_str = data_ref.strftime('%Y-%m-%d')
    c.execute("""
        SELECT carga_seg_qui, carga_sexta, hora_saida_seg_qui, hora_saida_sexta 
        FROM parametros_jornada 
        WHERE data_inicio <= %s AND (data_fim IS NULL OR data_fim >= %s)
        ORDER BY data_inicio DESC LIMIT 1
    """, (data_str, data_str))
    res = c.fetchone()
    if res: return float(res[0]), float(res[1]), res[2], res[3]
    return 8.17, 6.25, "17:05", "15:00"

def calcular_horas_uteis_puras(inicio, fim, data_ref):
    t1, t2 = datetime.combine(data_ref, inicio), datetime.combine(data_ref, fim)
    if t2 < t1: t2 += timedelta(days=1)
    
    pausas = [(time(7,30), time(7,35)), (time(9,0), time(9,10)), (time(11,30), time(12,30))]
    if data_ref.weekday() <= 3:
        pausas.append((time(15,0), time(15,10)))
    
    total_h = (t2 - t1).total_seconds() / 3600.0
    for pi, pf in pausas:
        i1, i2 = max(t1, datetime.combine(data_ref, pi)), min(t2, datetime.combine(data_ref, pf))
        if i2 > i1: total_h -= (i2 - i1).total_seconds() / 3600.0
        
    return max(0, total_h)

def registrar_evento_banco(matricula, data, horas, tipo, obs):
    cursor.execute("INSERT INTO banco_horas_log (matricula, data, horas_delta, operacao, justificativa) VALUES (%s,%s,%s,%s,%s)",
                   (matricula, data, float(horas), tipo, obs))
    conn.commit()

def verificar_sabado_consecutivo(matricula, data_registro):
    data_atual = datetime.strptime(data_registro, "%d/%m/%Y").date()
    sabado_passado = (data_atual - timedelta(days=7)).strftime("%d/%m/%Y")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM apontamentos WHERE matricula=%s AND data_registro=%s AND tipo IN ('Produção Normal', 'Retrabalho')", (matricula, sabado_passado))
    return c.fetchone()[0] > 0

def recalcular_dia(conn_db, matricula, data_br):
    c = conn_db.cursor()
    c.execute("SELECT id, hora_inicio, hora_fim, tipo, atividade FROM apontamentos WHERE matricula=%s AND data_registro=%s ORDER BY hora_inicio", (matricula, data_br))
    registros = c.fetchall()
    if not registros: return
    
    data_ref = datetime.strptime(data_br, "%d/%m/%Y").date()
    c.execute("SELECT 1 FROM feriados WHERE data = %s", (data_ref.strftime("%Y-%m-%d"),))
    is_feriado = c.fetchone()
    is_domingo = data_ref.weekday() == 6
    is_sabado = data_ref.weekday() == 5
    is_100 = is_feriado or is_domingo
    
    is_sabado_consecutivo = False
    if is_sabado:
        sabado_anterior = (data_ref - timedelta(days=7)).strftime("%d/%m/%Y")
        c.execute("SELECT COUNT(*) FROM apontamentos WHERE matricula=%s AND data_registro=%s AND tipo IN ('Produção Normal', 'Retrabalho')", (matricula, sabado_anterior))
        trabalhou_antes = c.fetchone()
        if trabalhou_antes and trabalhou_antes[0] > 0:
            is_sabado_consecutivo = True
    
    carga_sq, carga_sex, hs_sq, hs_sex = obter_parametros_dia(conn_db, data_ref)
    
    if data_ref.weekday() <= 3: carga_diaria = carga_sq
    elif data_ref.weekday() == 4: carga_diaria = carga_sex
    else: carga_diaria = 0.0 
        
    carga_restante = carga_diaria
    
    for reg in registros:
        db_id, hi_str, hf_str, tipo, atividade = reg
        try: hi = datetime.strptime(hi_str, "%H:%M:%S").time()
        except: hi = datetime.strptime(hi_str, "%H:%M").time()
        try: hf = datetime.strptime(hf_str, "%H:%M:%S").time()
        except: hf = datetime.strptime(hf_str, "%H:%M").time()
        
        net_h = calcular_horas_uteis_puras(hi, hf, data_ref)
        n, e50, e100, s_bh = 0.0, 0.0, 0.0, 0.0
        
        if is_100:
            if tipo not in ["Falta/Atraso", "Atestado / Justificada"]:
                e100 = round(net_h, 2)
            else:
                n = round(net_h, 2)
        elif is_sabado:
            if tipo not in ["Falta/Atraso", "Atestado / Justificada"]:
                if is_sabado_consecutivo:
                    e100 = round(net_h, 2)
                else:
                    s_bh = round(net_h, 2) 
            else:
                n = round(net_h, 2)
        else: 
            if tipo in ["Falta/Atraso", "Atestado / Justificada"]:
                if atividade and "Banco de Horas" in atividade:
                    n_calc = min(net_h, carga_restante)
                    carga_restante -= n_calc
                    s_bh = -round(net_h, 2) 
                    n = round(net_h, 2) 
                else:
                    n_calc = min(net_h, carga_restante)
                    carga_restante -= n_calc
                    n = round(net_h, 2)
            else:
                n_calc = min(net_h, carga_restante)
                e50_calc = net_h - n_calc
                carga_restante -= n_calc
                n, e50 = round(n_calc, 2), round(e50_calc, 2)
            
        c.execute("UPDATE apontamentos SET horas_normais=%s, he_50=%s, he_100=%s, saldo_bh=%s WHERE id=%s", (n, e50, e100, s_bh, db_id))
    conn_db.commit()

def resolver_sobreposicoes(conn_db, matricula, data_br, hi_novo, hf_novo, data_ref):
    c = conn_db.cursor()
    c.execute("SELECT * FROM apontamentos WHERE matricula = %s AND data_registro = %s", (matricula, data_br))
    registros = c.fetchall()
    if not registros: return
        
    colunas = [desc[0] for desc in c.description]
    idx_id = colunas.index('id')
    idx_hi = colunas.index('hora_inicio')
    idx_hf = colunas.index('hora_fim')
    
    for reg in registros:
        db_id = reg[idx_id]
        db_hi_str = reg[idx_hi]
        db_hf_str = reg[idx_hf]
        
        try: db_hi = datetime.strptime(db_hi_str, "%H:%M:%S").time()
        except: db_hi = datetime.strptime(db_hi_str, "%H:%M").time()
        try: db_hf = datetime.strptime(db_hf_str, "%H:%M:%S").time()
        except: db_hf = datetime.strptime(db_hf_str, "%H:%M").time()
        
        if db_hi < hf_novo and db_hf > hi_novo:
            if db_hi < hi_novo and db_hf > hf_novo:
                c.execute("UPDATE apontamentos SET hora_fim=%s WHERE id=%s", (str(hi_novo), db_id))
                dados_insert = list(reg)
                dados_insert[idx_hi] = str(hf_novo) 
                dados_insert[idx_hf] = str(db_hf)
                cols_insert = ", ".join(colunas[1:]) 
                vals_insert = tuple(dados_insert[1:])
                placeholders = ", ".join(["%s"] * len(vals_insert))
                c.execute(f"INSERT INTO apontamentos ({cols_insert}) VALUES ({placeholders})", vals_insert)
            elif db_hi < hi_novo and db_hf <= hf_novo:
                c.execute("UPDATE apontamentos SET hora_fim=%s WHERE id=%s", (str(hi_novo), db_id))
            elif db_hi >= hi_novo and db_hf > hf_novo:
                c.execute("UPDATE apontamentos SET hora_inicio=%s WHERE id=%s", (str(hf_novo), db_id))
            elif db_hi >= hi_novo and db_hf <= hf_novo:
                c.execute("DELETE FROM apontamentos WHERE id=%s", (db_id,))
    conn_db.commit()

def padronizar_datas_para_tela(df, colunas):
    for col in colunas:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%d/%m/%Y')
            df[col] = df[col].fillna("")
    return df

def formatar_datas_para_banco(df, colunas):
    for col in colunas:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
            df[col] = df[col].fillna("")
    return df

# FUNÇÕES DO RELATÓRIO RH E PDF
def color_ponto(val):
    if val == "-": return 'background-color: #f8f9fa; color: #ced4da;'
    if isinstance(val, (int, float)):
        if val < -0.05: return 'background-color: #f8d7da; color: #721c24;' 
        elif val > 0.05: return 'background-color: #fff3cd; color: #856404;' 
        else: return 'background-color: #d4edda; color: #155724;' 
    return ''

def limpa_texto_pdf(texto):
    if not texto or pd.isna(texto): return ""
    texto = str(texto)
    texto = texto.replace('⚠️', '[Atenção]').replace('✔️', '[OK]').replace('📋', '[Doc]')
    return texto.encode('latin-1', 'replace').decode('latin-1')

def preparar_imagem_pdf(caminho):
    if not caminho or caminho == 'N/A' or not os.path.exists(caminho): return None
    if os.path.getsize(caminho) == 0: return None 
    try:
        img = Image.open(caminho)
        if img.mode != 'RGB': img = img.convert('RGB')
        target_ratio = 4 / 3
        img_ratio = img.width / img.height
        if img_ratio > target_ratio: 
            new_w = int(img.height * target_ratio)
            offset = (img.width - new_w) / 2
            img = img.crop((offset, 0, offset + new_w, img.height))
        elif img_ratio < target_ratio: 
            new_h = int(img.width / target_ratio)
            offset = (img.height - new_h) / 2
            img = img.crop((0, offset, img.width, offset + new_h))
        caminho_pdf = caminho.replace(".jpg", "_pdf.jpg").replace(".png", "_pdf.jpg").replace(".jpeg", "_pdf.jpg")
        img = img.resize((800, 600))
        img.save(caminho_pdf, "JPEG", quality=85)
        return caminho_pdf
    except Exception: return None

# ==========================================
# 4. SIDEBAR OPERACIONAL
# ==========================================
with st.sidebar:
    logo = next((f for f in os.listdir(LOGO_DIR) if f.lower().startswith('logo')), None)
    if logo: st.image(os.path.join(LOGO_DIR, logo), width='stretch')
    st.write("---")
    
    h_iso, h_br = date.today().strftime("%Y-%m-%d"), date.today().strftime("%d/%m/%Y")
    
    cursor.execute("SELECT COUNT(*) FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''")
    total_o = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT matricula) FROM ferias_colaboradores WHERE %s BETWEEN data_inicio AND data_fim", (h_iso,))
    ferias_o = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT matricula) FROM apontamentos WHERE data_registro = %s AND tipo IN ('Atestado / Justificada', 'Falta/Atraso') AND atividade != 'Banco de Horas'", (h_br,))
    ausentes_o = cursor.fetchone()[0]
    
    st.metric("Capacidade Ativa Hoje", f"{max(0, total_o - ferias_o - ausentes_o)} Ops")
    st.caption("Visão focada em gestão de Ponto e Produção")

    st.write("---")
    with st.expander("⏱️ Conferência de Ponto (Excel)"):
        st.write("Exporte os apontamentos para cruzar com o relatório do RH.")
        tipo_ext = st.radio("Período:", ["Mês Atual", "Mês Anterior", "Semana Atual"])
        
        df_ponto = pd.read_sql_query("""
            SELECT data_registro as Data, matricula as Matricula, operador as Operador, hora_inicio as Inicio, hora_fim as Fim, 
                   horas_normais as "Normais(h)", he_50 as "HE50(h)", he_100 as "HE100(h)", saldo_bh as "Banco(h)",
                   tipo as Tipo, atividade as Atividade, so as SO, customer as Cliente, wo as WO, product_name as Produto, 
                   unidade as Unidade, descricao as Observacoes
            FROM apontamentos
        """, engine)
        
        df_ponto['data_dt'] = pd.to_datetime(df_ponto['Data'], format='%d/%m/%Y', errors='coerce')
        
        hoje_ponto = date.today()
        if tipo_ext == "Mês Atual":
            df_fil = df_ponto[(df_ponto['data_dt'].dt.year == hoje_ponto.year) & (df_ponto['data_dt'].dt.month == hoje_ponto.month)]
            arq_nome = f"Conferencia_Ponto_Mensal_{hoje_ponto.strftime('%m_%Y')}.xlsx"
        elif tipo_ext == "Mês Anterior":
            primeiro_dia_mes_atual = hoje_ponto.replace(day=1)
            mes_ant = primeiro_dia_mes_atual - timedelta(days=1)
            df_fil = df_ponto[(df_ponto['data_dt'].dt.year == mes_ant.year) & (df_ponto['data_dt'].dt.month == mes_ant.month)]
            arq_nome = f"Conferencia_Ponto_Mes_Anterior_{mes_ant.strftime('%m_%Y')}.xlsx"
        else:
            start_week = hoje_ponto - timedelta(days=hoje_ponto.weekday())
            end_week = start_week + timedelta(days=6)
            df_fil = df_ponto[(df_ponto['data_dt'].dt.date >= start_week) & (df_ponto['data_dt'].dt.date <= end_week)]
            arq_nome = f"Conferencia_Ponto_Semanal_{start_week.strftime('%d%m')}_a_{end_week.strftime('%d%m')}.xlsx"
            
        if not df_fil.empty:
            df_fil = df_fil.sort_values(by=['Operador', 'data_dt', 'Inicio'])
            df_fil = df_fil.drop(columns=['data_dt']) 
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_fil.to_excel(writer, index=False, sheet_name='Ponto')
            
            st.download_button(label="📥 Baixar Excel do Ponto", data=output.getvalue(), file_name=arq_nome, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        else:
            st.info("Nenhum apontamento registrado neste período.")

# ==========================================
# 5. DETECÇÃO DE PAPEL (SECURITY RBAC)
# ==========================================
user_role = st.query_params.get("role", "admin").lower()

# ==========================================
# 6. ABAS PRINCIPAIS
# ==========================================
tab_lancamento, tab_dash_proj, tab_dash_rh, tab_ordens, tab_plan, tab_manutencao, tab_pdf = st.tabs([
    "📝 Lançamentos", 
    "📊 Dash. Projetos", 
    "👥 Dash. RH",
    "📋 Ordens de Produção",
    "📅 Planejamento de Carga",
    "🔍 Manutenção", 
    "📑 Relatórios PDF"
])
# ------------------------------------------
# ABA: LANÇAMENTO & AUDITORIA
# ------------------------------------------
with tab_lancamento:
    if user_role == "viewer":
        st.error("🔒 Acesso Restrito - Modo de Visualização Gerencial (Apenas Leitura)")
    else:
        if 'data_lan_input' not in st.session_state:
            st.session_state.data_lan_input = date.today()
        
        if 'hf_input' not in st.session_state:
            d_init = st.session_state.data_lan_input
            _, _, hs_sq_init, hs_sex_init = obter_parametros_dia(conn, d_init)
            try:
                st.session_state.hf_input = datetime.strptime(hs_sex_init if d_init.weekday() == 4 else hs_sq_init, "%H:%M").time()
            except:
                st.session_state.hf_input = time(15,0) if d_init.weekday() == 4 else time(17,5)
                
        if 'hi_input' not in st.session_state:
            st.session_state.hi_input = time(7, 30)

        df_colab = pd.read_sql_query("SELECT matricula, nome, linha FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''", engine)
        df_proj_so = pd.read_sql_query("SELECT DISTINCT so, customer FROM projetos", engine)
        df_erros = pd.read_sql_query("SELECT erro FROM tipos_erro", engine)
        df_causadores = pd.read_sql_query("SELECT causador FROM causadores_erro", engine)
        df_paradas = pd.read_sql_query("SELECT categoria FROM categorias_parada", engine)

        with st.container(border=True):
            col_top_left, col_top_right = st.columns([1, 2])
            
            with col_top_left:
                st.markdown("**👤 Identificação**")
                colab_sel = st.selectbox("Operador", ["- Selecione -"] + [f"{r['matricula']} - {r['nome']}" for _, r in df_colab.iterrows()], key="colab_sel_box")
                
                def on_date_change():
                    d = st.session_state.data_lan_input
                    _, _, hs_sq_cb, hs_sex_cb = obter_parametros_dia(conn, d)
                    try:
                        st.session_state.hf_input = datetime.strptime(hs_sex_cb if d.weekday() == 4 else hs_sq_cb, "%H:%M").time()
                    except:
                        st.session_state.hf_input = time(15,0) if d.weekday() == 4 else time(17,5)

                data_lan = st.date_input("Data do Apontamento", format="DD/MM/YYYY", key="data_lan_input", on_change=on_date_change)
                
            with col_top_right:
                auditoria_placeholder = st.empty()

        st.markdown("### 📝 Lançar Atividade")
        with st.container(border=True):
            tipo_ap = st.radio("Selecione o Tipo de Atividade:", ["Produção Normal", "Retrabalho", "Parada", "Falta/Atraso", "Atestado / Justificada"], horizontal=True, key="tipo_ap_radio")
            st.write("") 
            
            col1, col2 = st.columns(2)
            with col1:
                linha_colab = "N/A"
                if colab_sel != "- Selecione -":
                    mat_selecionada = colab_sel.split(" - ")[0]
                    resultado_linha = df_colab[df_colab['matricula'] == mat_selecionada]['linha'].iloc[0]
                    if pd.notna(resultado_linha) and str(resultado_linha).strip() != "":
                        linha_colab = resultado_linha

                if tipo_ap in ["Produção Normal", "Retrabalho", "Parada"]:
                    if tipo_ap == "Produção Normal":
                        df_so_ativas = pd.read_sql_query("SELECT DISTINCT so, customer FROM projetos WHERE UPPER(TRIM(status_producao)) != 'FINALIZADO' OR status_producao IS NULL", engine)
                        so_list = ["- Selecione -", "Geral (Sem SO Vinculada)"] + [f"{r['so']} - {r['customer']}" for _, r in df_so_ativas.iterrows()]
                    else:
                        so_list = ["- Selecione -", "Geral (Sem SO Vinculada)"] + [f"{r['so']} - {r['customer']}" for _, r in df_proj_so.iterrows()]
                    
                    so_sel_full = st.selectbox("Sales Order (SO) - Cliente", so_list, key="so_sel_box")
                    wo_list = ["Não Vinculada"]
                    so_id_db = "N/A"
                    cliente_val = "N/A"
                    res_wo = pd.DataFrame()
                    
                    if so_sel_full not in ["- Selecione -", "Geral (Sem SO Vinculada)"]:
                        partes_so = so_sel_full.split(" - ")
                        so_id_db = partes_so[0]
                        if len(partes_so) > 1:
                            cliente_val = partes_so[1].strip()
                        
                        if tipo_ap == "Produção Normal":
                            res_wo = pd.read_sql_query("SELECT wo, product_name, qtde FROM projetos WHERE so = %(so_id)s AND (UPPER(TRIM(status_producao)) != 'FINALIZADO' OR status_producao IS NULL)", engine, params={"so_id": so_id_db})
                        else:
                            res_wo = pd.read_sql_query("SELECT wo, product_name, qtde FROM projetos WHERE so = %(so_id)s", engine, params={"so_id": so_id_db})
                        
                        wo_list = ["Não Vinculada"] + [f"{r['wo']} - {r['product_name']}" for _, r in res_wo.iterrows()]
                        
                    wo_sel_full = st.selectbox("Work Order (WO) - Produto", wo_list, key="wo_sel_box")
                    wo_id_db = wo_sel_full.split(" - ")[0] if wo_sel_full != "Não Vinculada" else "N/A"
                    
                    prod_name_val = "N/A"
                    lista_unidades = ["Geral"]
                    
                    if wo_sel_full != "Não Vinculada" and not res_wo.empty:
                        filtro_wo = res_wo[res_wo['wo'] == wo_id_db]
                        if not filtro_wo.empty:
                            prod_name_val = filtro_wo['product_name'].iloc[0]
                            qtde_wo = filtro_wo['qtde'].iloc[0]
                            try:
                                qtde_int = int(qtde_wo)
                                if qtde_int > 0:
                                    lista_unidades = ["Geral"] + [f"Unidade {i}" for i in range(1, qtde_int + 1)]
                            except: pass
                    
                    unidade_sel = st.selectbox("Unidade / Item da Ordem", lista_unidades, key="unidade_sel_box")
                    
                    if tipo_ap == "Parada":
                        lista_paradas = df_paradas['categoria'].tolist() if not df_paradas.empty else ["- Cadastre Categorias -"]
                        atividade = st.selectbox("Categoria da Parada", lista_paradas, key="atividade_box_parada")
                    else:
                        atividade = linha_colab
                    
                else:
                    so_id_db, cliente_val, wo_sel_full, prod_name_val, unidade_sel = "N/A", "N/A", "N/A", "N/A", "N/A"
                    if tipo_ap == "Falta/Atraso":
                        atividade = st.selectbox("Classificação da Ausência", ["Falta / Atraso Não Justificado", "Banco de Horas", "Declaração Médica"], key="atividade_box_falta")
                    else:
                        atividade = "Atestado / Justificada"

            with col2:
                t_c1, t_c2 = st.columns(2)
                hi = t_c1.time_input("Hora Início", step=60, key="hi_input")
                hf = t_c2.time_input("Hora Fim", step=60, key="hf_input")
                
                net_h = calcular_horas_uteis_puras(hi, hf, data_lan)
                
                if tipo_ap in ["Produção Normal", "Retrabalho", "Parada"]:
                    st.info(f"Duração Líquida do Apontamento: {net_h:.2f}h")
                    
                    if tipo_ap == "Retrabalho":
                        t_erro = st.selectbox("Tipo do Erro", df_erros['erro'].tolist() if not df_erros.empty else ["- Cadastre Erros na Manutenção -"], key="t_erro_box")
                        c_erro = st.selectbox("Causador", df_causadores['causador'].tolist() if not df_causadores.empty else ["- Cadastre Causadores na Manutenção -"], key="c_erro_box")
                        foto_antes = st.file_uploader("Foto ANTES (Obrigatório)", type=["png", "jpg", "jpeg"], key="foto_uploader_antes")
                        foto_depois = st.file_uploader("Foto DEPOIS (Obrigatório)", type=["png", "jpg", "jpeg"], key="foto_uploader_depois")
                    else:
                        t_erro, c_erro, foto_antes, foto_depois = "N/A", "N/A", None, None
                else:
                    st.warning(f"Horas Classificadas ({tipo_ap}): {net_h:.2f}h")
                    t_erro, c_erro, foto_antes, foto_depois = "N/A", "N/A", None, None

            obs = st.text_area(f"Observações {'(Obrigatório)' if tipo_ap in ['Retrabalho', 'Parada'] else '(Opcional)'}", key="obs_input")
            
            fora_do_plano = False
            motivo_desvio = ""
            
            if colab_sel != "- Selecione -" and tipo_ap in ["Produção Normal", "Retrabalho"]:
                mat_eval = colab_sel.split(" - ")[0]
                data_iso_eval = data_lan.strftime("%Y-%m-%d")
                
                if 'wo_sel_full' in locals() and wo_sel_full not in ["- Selecione -", "Não Vinculada", "N/A"]:
                    wo_eval = wo_sel_full.split(" - ")[0]
                    cursor.execute("SELECT COUNT(*) FROM planejamento WHERE matricula=%s AND data_planejada=%s AND wo=%s", (mat_eval, data_iso_eval, wo_eval))
                    check_plan = cursor.fetchone()[0]
                    
                    if check_plan == 0:
                        fora_do_plano = True
                        st.warning("⚠️ **Aviso de PCP:** Esta Ordem de Produção (WO) não está no seu planejamento (Gantt) para hoje.")
                        motivo_desvio = st.text_input("Justificativa para Apontamento Extra-Plano (Obrigatório):", key="motivo_desvio_input")

            if st.button("💾 SALVAR APONTAMENTO", type="primary", use_container_width=True):
                if colab_sel == "- Selecione -":
                    st.error("❌ Selecione um operador.")
                else:
                    mat_validar = colab_sel.split(" - ")[0]
                    data_iso = data_lan.strftime("%Y-%m-%d")
                    data_br = data_lan.strftime("%d/%m/%Y")
                    
                    cursor.execute("SELECT 1 FROM ferias_colaboradores WHERE matricula = %s AND %s BETWEEN data_inicio AND data_fim", (mat_validar, data_iso))
                    em_ferias = cursor.fetchone()
                    
                    if em_ferias:
                        st.error(f"❌ BLOQUEIO: O operador {colab_sel} encontra-se em FÉRIAS na data {data_br}.")
                    elif tipo_ap == "Parada" and atividade == "- Cadastre Categorias -":
                        st.error("❌ Cadastre as categorias de parada primeiro.")
                    elif tipo_ap == "Retrabalho" and (not obs or not foto_antes or not foto_depois):
                        st.error("❌ As fotos (Antes e Depois) e a Observação são OBRIGATÓRIAS para registrar Retrabalho.")
                    elif tipo_ap == "Parada" and not obs:
                        st.error("❌ A Observação (motivo) é OBRIGATÓRIA para registrar uma Parada.")
                    elif tipo_ap in ["Produção Normal", "Retrabalho"] and so_id_db == "N/A":
                        st.error("❌ Selecione uma SO válida (Se for parada genérica, use 'Geral (Sem SO Vinculada)').")
                    elif fora_do_plano and not motivo_desvio.strip():
                        st.error("❌ Como esta Ordem não foi planejada pelo PCP para você hoje, a Justificativa é OBRIGATÓRIA.")
                    else:
                        wo_id_db = wo_sel_full.split(" - ")[0] if " - " in wo_sel_full else wo_sel_full
                        path_f_antes, path_f_depois = "", ""
                        
                        if tipo_ap == "Retrabalho" and foto_antes and foto_depois:
                            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                            path_f_antes = os.path.join(PASTA_FOTOS, f"{timestamp}_{so_id_db}_ANTES.jpg")
                            path_f_depois = os.path.join(PASTA_FOTOS, f"{timestamp}_{so_id_db}_DEPOIS.jpg")
                            with open(path_f_antes, "wb") as f: f.write(foto_antes.getbuffer())
                            with open(path_f_depois, "wb") as f: f.write(foto_depois.getbuffer())
                        
                        if fora_do_plano:
                            obs = f"{obs}\n[⚠️ DESVIO PCP]: {motivo_desvio}".strip()
                        
                        resolver_sobreposicoes(conn, mat_validar, data_br, hi, hf, data_lan)
                        
                        cursor.execute('''INSERT INTO apontamentos (data_registro, matricula, operador, so, customer, wo, product_name, unidade, atividade, tipo, tipo_erro, causador_erro, hora_inicio, hora_fim, horas_normais, he_50, he_100, saldo_bh, descricao, foto_path, foto_depois_path) 
                                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,0,%s,%s,%s)''',
                                       (data_br, mat_validar, colab_sel.split(" - ")[1], so_id_db, cliente_val, wo_id_db, prod_name_val, unidade_sel, atividade, tipo_ap, t_erro, c_erro, str(hi), str(hf), obs, path_f_antes, path_f_depois))
                        conn.commit()
                        
                        if data_lan.weekday() == 5:
                            if not verificar_sabado_consecutivo(mat_validar, data_br):
                                registrar_evento_banco(mat_validar, data_br, round(net_h, 2), "CREDITO", "Sábado Trabalhado (Pimeiro do Ciclo)")
                        if tipo_ap == "Falta/Atraso" and atividade == "Banco de Horas":
                            registrar_evento_banco(mat_validar, data_br, -round(net_h, 2), "DEBITO", "Saída Antecipada / Folga")
                        
                        recalcular_dia(conn, mat_validar, data_br)
                        st.success("✔️ Apontamento registrado! Carga horária e Banco de Horas atualizados.")
                        
                        time_sys.sleep(1.5)
                        
                        for key in list(st.session_state.keys()): 
                            if key not in ['hi_input', 'hf_input']:
                                del st.session_state[key]
                                
                        if 'hi_input' in st.session_state: del st.session_state['hi_input']
                        if 'hf_input' in st.session_state: del st.session_state['hf_input']
                            
                        st.session_state['colab_sel_box'] = "- Selecione -"
                        st.session_state['tipo_ap_radio'] = "Produção Normal"
                        st.session_state['so_sel_box'] = "- Selecione -"
                        st.session_state['wo_sel_box'] = "Não Vinculada"
                        st.session_state['unidade_sel_box'] = "Geral"
                        st.session_state['obs_input'] = ""
                        
                        st.rerun()

        # ==========================================
        # LANÇAMENTO COLETIVO (S&OP / BANCO DE HORAS)
        # ==========================================
        st.markdown("---")
        st.markdown("### ⚡ Lançamento Coletivo (Desconto de Banco de Horas)")
        with st.expander("Aplicar saída antecipada ou banco de horas para múltiplos operadores de uma vez", expanded=False):
            st.info("Utilize este painel quando precisar dispensar a fábrica ou uma linha inteira mais cedo. O sistema calculará o débito negativo automaticamente para todos os ativos no setor selecionado.")
            
            c_lote1, c_lote2, c_lote3 = st.columns(3)
            data_lote = c_lote1.date_input("Data da Ação", date.today(), format="DD/MM/YYYY")
            linhas_unicas = df_colab['linha'].dropna().unique().tolist()
            linha_lote = c_lote2.selectbox("Setor Afetado", ["- Todos os Setores (Fábrica Inteira) -"] + linhas_unicas)
            
            _, _, hs_sq_lote, hs_sx_lote = obter_parametros_dia(conn, data_lote)
            try:
                hora_padrao_fim = datetime.strptime(hs_sx_lote if data_lote.weekday() == 4 else hs_sq_lote, "%H:%M").time()
            except:
                hora_padrao_fim = time(15,0) if data_lote.weekday() == 4 else time(17,5)
            
            hi_lote = c_lote1.time_input("Início da Ausência (A partir de que horas não trabalharam?)", time(15,40) if data_lote.weekday() <= 3 else time(11,30), step=60)
            hf_lote = c_lote2.time_input("Fim da Ausência (Horário que o turno encerraria)", hora_padrao_fim, step=60)
            motivo_lote = c_lote3.text_input("Motivo", "Saída antecipada por baixa demanda S&OP")
            
            if st.button("🚀 Processar Desconto de Banco de Horas em Lote", type="primary", use_container_width=True):
                if hi_lote >= hf_lote:
                    st.error("A hora de início deve ser menor que a hora de término.")
                else:
                    if linha_lote == "- Todos os Setores (Fábrica Inteira) -":
                        ops_afetados = df_colab
                    else:
                        ops_afetados = df_colab[df_colab['linha'] == linha_lote]
                        
                    if ops_afetados.empty:
                        st.warning("Nenhum operador ativo encontrado para este filtro.")
                    else:
                        progresso = st.progress(0)
                        total_ops = len(ops_afetados)
                        data_br_lote = data_lote.strftime("%d/%m/%Y")
                        horas_desconto = calcular_horas_uteis_puras(hi_lote, hf_lote, data_lote)
                        
                        for i, (_, row_op) in enumerate(ops_afetados.iterrows()):
                            resolver_sobreposicoes(conn, row_op['matricula'], data_br_lote, hi_lote, hf_lote, data_lote)
                            
                            cursor.execute('''INSERT INTO apontamentos (data_registro, matricula, operador, so, customer, wo, product_name, unidade, atividade, tipo, tipo_erro, causador_erro, hora_inicio, hora_fim, horas_normais, he_50, he_100, saldo_bh, descricao, foto_path, foto_depois_path) 
                                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,0,%s,%s,%s)''',
                                           (data_br_lote, row_op['matricula'], row_op['nome'], "N/A", "N/A", "N/A", "N/A", "Geral", "Banco de Horas", "Falta/Atraso", "N/A", "N/A", str(hi_lote), str(hf_lote), motivo_lote, "", ""))
                            conn.commit()
                            
                            registrar_evento_banco(row_op['matricula'], data_br_lote, -round(horas_desconto, 2), "DEBITO_LOTE", motivo_lote)
                            recalcular_dia(conn, row_op['matricula'], data_br_lote)
                            progresso.progress((i + 1) / total_ops)
                            
                        st.success(f"✔️ Lote concluído! Banco de Horas deduzido para {total_ops} funcionários.")
                        time_sys.sleep(2.0)
                        st.rerun()

        # ==========================================
        # POPULANDO A AUDITORIA DIÁRIA NO TOPO DA TELA
        # ==========================================
        with auditoria_placeholder.container():
            if colab_sel != "- Selecione -":
                data_br_auditoria = data_lan.strftime("%d/%m/%Y")
                st.markdown(f"**🔎 Auditoria Diária ({data_br_auditoria})**")
                
                carga_sq_auditoria, carga_sx_auditoria, _, _ = obter_parametros_dia(conn, data_lan)
                
                if data_lan.weekday() <= 3: meta_h = carga_sq_auditoria 
                elif data_lan.weekday() == 4: meta_h = carga_sx_auditoria
                else: meta_h = 0.0

                mat_auditoria = colab_sel.split(" - ")[0]
                df_auditoria = pd.read_sql_query("SELECT hora_inicio, hora_fim, atividade, tipo, horas_normais, he_50, he_100, saldo_bh FROM apontamentos WHERE matricula = %(mat)s AND data_registro = %(dt)s ORDER BY hora_inicio", engine, params={"mat": mat_auditoria, "dt": data_br_auditoria})
                
                total_lancado = df_auditoria['horas_normais'].sum() + df_auditoria['he_50'].sum() + df_auditoria['he_100'].sum()
                saldo_bh_dia = df_auditoria['saldo_bh'].sum()
                saldo_produtividade = total_lancado - meta_h

                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Meta", f"{meta_h:.2f}h")
                col_m2.metric("Lançado", f"{total_lancado:.2f}h")
                col_m3.metric("Produtividade", f"{saldo_produtividade:.2f}h", delta=round(saldo_produtividade, 2))
                col_m4.metric("Extrato BH (Dia)", f"{saldo_bh_dia:.2f}h", delta=round(saldo_bh_dia, 2), delta_color="normal" if saldo_bh_dia >= 0 else "inverse")

                if not df_auditoria.empty:
                    df_auditoria = df_auditoria.rename(columns={
                        "hora_inicio": "Início", "hora_fim": "Fim", "atividade": "Atividade", 
                        "tipo": "Tipo", "horas_normais": "Normal", "he_50": "HE50", "he_100": "HE100", "saldo_bh": "Banco (h)"
                    })
                    st.dataframe(df_auditoria, use_container_width=True, height=145)
                else:
                    st.info("Nenhum lançamento efetuado nesta data.")
            else:
                st.info("👈 Selecione um operador à esquerda para visualizar sua auditoria.")

        # ==========================================
        # PAINEL DE GESTÃO DE APONTAMENTOS
        # ==========================================
        st.markdown("---")
        st.markdown("### 🛠️ Gerenciar / Corrigir Apontamentos")
        with st.expander("Clique aqui para corrigir horários ou apagar lançamentos errados", expanded=False):
            st.caption("Dica: Se um apontamento de Banco de Horas sumiu do gráfico, selecione ele aqui e clique em 'Salvar Novo Horário' para forçar o recálculo automático.")
            data_edit = st.date_input("1. Selecione a data do apontamento:", date.today(), format="DD/MM/YYYY", key="data_edit_apont")
            data_br_edit = data_edit.strftime("%d/%m/%Y")
            
            df_apont_edit = pd.read_sql_query("SELECT id, matricula, operador, hora_inicio, hora_fim, tipo, atividade, wo, descricao FROM apontamentos WHERE data_registro = %(dt)s", engine, params={"dt": data_br_edit})
            
            if not df_apont_edit.empty:
                lista_apont = ["- Selecione -"] + [f"ID {r['id']} | {r['operador']} | {r['hora_inicio']} às {r['hora_fim']} | {r['tipo']}" for _, r in df_apont_edit.iterrows()]
                apont_sel = st.selectbox("2. Selecione o apontamento que deseja corrigir:", lista_apont, key="apont_sel_edit")
                
                if apont_sel != "- Selecione -":
                    id_apont = str(apont_sel.split(" | ")[0].replace("ID ", "")).strip()
                    filtro_ap = df_apont_edit[df_apont_edit['id'].astype(str) == id_apont]
                    
                    if not filtro_ap.empty:
                        row_apont = filtro_ap.iloc[0]
                        st.info(f"**Detalhes do Apontamento:**\n\n**WO:** {row_apont['wo']} | **Atividade:** {row_apont['atividade']} | **Obs:** {row_apont['descricao']}")
                        
                        c_e1, c_e2 = st.columns(2)
                        try:
                            hi_edit_val = datetime.strptime(row_apont['hora_inicio'], "%H:%M:%S").time()
                        except:
                            hi_edit_val = datetime.strptime(row_apont['hora_inicio'], "%H:%M").time()
                        
                        try:
                            hf_edit_val = datetime.strptime(row_apont['hora_fim'], "%H:%M:%S").time()
                        except:
                            hf_edit_val = datetime.strptime(row_apont['hora_fim'], "%H:%M").time()

                        hi_edit = c_e1.time_input("Nova Hora de Início", value=hi_edit_val, step=60, key="hi_edit")
                        hf_edit = c_e2.time_input("Nova Hora de Fim", value=hf_edit_val, step=60, key="hf_edit")
                        
                        st.write("")
                        c_btn_e1, c_btn_e2 = st.columns([1, 1])
                        if c_btn_e1.button("💾 Salvar Novo Horário", type="primary", use_container_width=True):
                            cursor.execute("UPDATE apontamentos SET hora_inicio=%s, hora_fim=%s WHERE id=%s", (str(hi_edit), str(hf_edit), id_apont))
                            conn.commit()
                            recalcular_dia(conn, row_apont['matricula'], data_br_edit)
                            st.success("✔️ Horário atualizado e recálculo efetuado com sucesso!")
                            time_sys.sleep(1.5)
                            st.rerun()
                            
                        if c_btn_e2.button("🗑️ Excluir Apontamento", use_container_width=True):
                            cursor.execute("DELETE FROM apontamentos WHERE id=%s", (id_apont,))
                            conn.commit()
                            recalcular_dia(conn, row_apont['matricula'], data_br_edit)
                            st.success("✔️ Apontamento excluído da base e auditoria reprocessada!")
                            time_sys.sleep(1.5)
                            st.rerun()
                    else:
                        st.error("Apontamento não encontrado no banco de dados.")
            else:
                st.info("Nenhum apontamento registrado na data selecionada.")
# ------------------------------------------
# ABA: DASHBOARD PROJETOS E PRODUÇÃO
# ------------------------------------------
with tab_dash_proj:
    st.markdown("## 📊 Painel de Indicadores de Projetos")
    
    st.markdown("### ⏱️ Rentabilidade Geral do Projeto: Horas Consumidas vs Vendidas")
    df_so_dash = pd.read_sql_query("SELECT so, customer, SUM(horas_vendidas) as total_vendido FROM projetos GROUP BY so, customer", engine)
    
    if not df_so_dash.empty:
        so_dash_sel = st.selectbox("Selecione a Ordem de Venda (SO):", [f"{r['so']} - {r['customer']}" for _, r in df_so_dash.iterrows()])
        so_dash_clean = so_dash_sel.split(" - ")[0]
        
        vendidas = df_so_dash[df_so_dash['so'] == so_dash_clean]['total_vendido'].iloc[0] or 0.0
        
        df_cons = pd.read_sql_query("""
            SELECT tipo, SUM(horas_normais + he_50 + he_100) as consumido 
            FROM apontamentos 
            WHERE so=%(so_dash)s AND tipo IN ('Produção Normal', 'Retrabalho', 'Parada')
            GROUP BY tipo
        """, engine, params={"so_dash": so_dash_clean})
        
        consumo_prod = df_cons[df_cons['tipo'] == 'Produção Normal']['consumido'].sum() if not df_cons.empty else 0.0
        consumo_ret = df_cons[df_cons['tipo'] == 'Retrabalho']['consumido'].sum() if not df_cons.empty else 0.0
        consumo_par = df_cons[df_cons['tipo'] == 'Parada']['consumido'].sum() if not df_cons.empty else 0.0
        consumo_perdas = consumo_ret + consumo_par
        
        total_consumido = consumo_prod + consumo_perdas
        saldo_restante = vendidas - total_consumido
        
        percentual_uso = (total_consumido / vendidas * 100) if vendidas > 0 else 0.0
        perc_prod_orc = (consumo_prod / vendidas * 100) if vendidas > 0 else 0.0
        
        perc_prod_interno = (consumo_prod / total_consumido * 100) if total_consumido > 0 else 0.0
        perc_perd_interno = (consumo_perdas / total_consumido * 100) if total_consumido > 0 else 0.0
        
        col_g1a, col_g1b, col_g2 = st.columns([1, 1, 2])
        
        with col_g1a:
            st.write("")
            st.markdown(f"<p style='margin-bottom:0px; color:#555;'>Orçamento Vendido</p><h3 style='margin-top:0px;'>{vendidas:.2f}h</h3>", unsafe_allow_html=True)
            st.markdown(f"<p style='margin-bottom:0px; color:#555;'>Total Consumido</p><h3 style='margin-top:0px;'>{total_consumido:.2f}h</h3>", unsafe_allow_html=True)
            
            cor_saldo = "#dc3545" if saldo_restante < 0 else "#28a745"
            st.markdown(f"<p style='margin-bottom:0px; color:#555;'>Saldo (Gordura)</p><h3 style='margin-top:0px; color:{cor_saldo};'>{saldo_restante:.2f}h</h3>", unsafe_allow_html=True)

        with col_g1b:
            st.write("")
            st.markdown(f"<p style='margin-bottom:0px; color:#555; font-weight:bold;'>Detalhe do Consumo:</p>", unsafe_allow_html=True)
            st.write("")
            st.markdown(f"<div style='border-left: 5px solid #004a99; padding-left: 10px; margin-bottom: 15px;'><span style='color:#555;'>Produção (Útil)</span><br><span style='font-size:22px; font-weight:bold; color:#004a99;'>{consumo_prod:.2f}h</span></div>", unsafe_allow_html=True)
            st.markdown(f"<div style='border-left: 5px solid #dc3545; padding-left: 10px;'><span style='color:#555;'>Retrabalho / Parada</span><br><span style='font-size:22px; font-weight:bold; color:#dc3545;'>{consumo_perdas:.2f}h</span></div>", unsafe_allow_html=True)
        
        with col_g2:
            if vendidas > 0:
                val_gauge_main = percentual_uso
                val_step_main = perc_prod_orc
                sufixo_main = "%"
                max_g_main = max(120, val_gauge_main + 10)
                titulo_main = "Análise de Horas"
                cor_num_main = "#333"
            else:
                val_gauge_main = total_consumido
                val_step_main = consumo_prod
                sufixo_main = "h" if total_consumido > 0 else "%"
                max_g_main = max(10, total_consumido * 1.5) if total_consumido > 0 else 100
                titulo_main = "<span style='color:#dc3545;'>⚠️ Custo Não Previsto</span>" if total_consumido > 0 else "Análise de Horas"
                cor_num_main = "#dc3545" if total_consumido > 0 else "#333"
                
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number",
                value = val_gauge_main,
                number = {'suffix': sufixo_main, 'font': {'size': 50, 'color': cor_num_main}}, 
                title = {'text': titulo_main, 'font': {'size': 18, 'color': '#333'}},
                gauge = {
                    'axis': {'range': [0, max_g_main], 'tickwidth': 1, 'tickcolor': "darkblue"},
                    'bar': {'color': "rgba(0,0,0,0)", 'thickness': 0}, 
                    'bgcolor': "#e9ecef", 
                    'steps': [
                        {'range': [0, val_step_main], 'color': "#004a99"}, 
                        {'range': [val_step_main, val_gauge_main], 'color': "#dc3545"}  
                    ],
                    'threshold': {
                        'line': {'color': "black", 'width': 4},
                        'thickness': 0.75,
                        'value': 100 if vendidas > 0 else 0 
                    }
                }
            ))
            
            fig_gauge.update_layout(height=300, margin=dict(l=30, r=30, t=40, b=10))
            st.plotly_chart(fig_gauge, use_container_width=True, config={'displayModeBar': False}, key="gauge_main_proj")
            
            st.markdown(f"""
            <div style='text-align: center; font-size: 14px; margin-top: -10px;'>
                <span style='color:#004a99; font-weight:bold;'>■ Produção (Útil): {perc_prod_interno:.1f}%</span> 
                &nbsp;&nbsp;&nbsp; 
                <span style='color:#dc3545; font-weight:bold;'>■ Retrabalho/Parada: {perc_perd_interno:.1f}%</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    
    st.markdown("### 🏭 Rentabilidade por Setor (Linha de Produção)")
    
    df_linhas_ven = pd.read_sql_query("SELECT linha, SUM(horas_vendidas) as vendidas FROM projetos WHERE so = %(so)s AND linha IS NOT NULL AND TRIM(linha) != '' AND linha != 'None' GROUP BY linha", engine, params={"so": so_dash_clean})
    df_linhas_cons = pd.read_sql_query("""
        SELECT c.linha, 
               SUM(CASE WHEN a.tipo = 'Produção Normal' THEN a.horas_normais + a.he_50 + a.he_100 ELSE 0 END) as consumo_prod,
               SUM(CASE WHEN a.tipo IN ('Retrabalho', 'Parada') THEN a.horas_normais + a.he_50 + a.he_100 ELSE 0 END) as consumo_perdas
        FROM apontamentos a 
        LEFT JOIN colaboradores c ON a.matricula = c.matricula
        WHERE a.so = %(so)s AND a.tipo IN ('Produção Normal', 'Retrabalho', 'Parada') 
        AND c.linha IS NOT NULL AND TRIM(c.linha) != '' AND c.linha != 'None'
        GROUP BY c.linha
    """, engine, params={"so": so_dash_clean})
    
    if not df_linhas_ven.empty:
        df_linhas = pd.merge(df_linhas_ven, df_linhas_cons, on='linha', how='outer').fillna(0)
        
        cols_linhas = st.columns(3)
        idx = 0
        for _, row_l in df_linhas.iterrows():
            l_nome = row_l['linha']
            l_ven = row_l['vendidas']
            l_prod = row_l['consumo_prod']
            l_perd = row_l['consumo_perdas']
            l_cons = l_prod + l_perd
            
            if l_ven > 0:
                val_gauge_l = (l_cons / l_ven * 100)
                val_step_l = (l_prod / l_ven * 100)
                sufixo_l = "%"
                max_g_l = max(120, val_gauge_l + 10)
                cor_num_l = "#333"
                titulo_l = f"<h4 style='text-align: center; color: #333; margin-bottom: 0px;'>{l_nome}</h4>"
            else:
                val_gauge_l = l_cons
                val_step_l = l_prod
                sufixo_l = "h" if l_cons > 0 else "%"
                max_g_l = max(10, l_cons * 1.5) if l_cons > 0 else 100
                cor_num_l = "#dc3545" if l_cons > 0 else "#333"
                alerta = " <span style='color:#dc3545; font-size:14px;'><br>(⚠️ Extra)</span>" if l_cons > 0 else ""
                titulo_l = f"<h4 style='text-align: center; color: #333; margin-bottom: 0px;'>{l_nome}{alerta}</h4>"
            
            perc_prod_int_l = (l_prod / l_cons * 100) if l_cons > 0 else 0.0
            perc_perd_int_l = (l_perd / l_cons * 100) if l_cons > 0 else 0.0
            
            with cols_linhas[idx % 3]:
                st.markdown(titulo_l, unsafe_allow_html=True)
                st.markdown(f"<p style='text-align: center; font-size:14px; color:gray; margin-top: 0px;'>Orçamento: {l_ven:.0f}h | Consumo: {l_cons:.0f}h</p>", unsafe_allow_html=True)
                
                fig_l = go.Figure(go.Indicator(
                    mode = "gauge+number",
                    value = val_gauge_l,
                    number = {'suffix': sufixo_l, 'font': {'size': 35, 'color': cor_num_l}}, 
                    gauge = {
                        'axis': {'range': [0, max_g_l], 'tickwidth': 1, 'tickcolor': "darkblue"},
                        'bar': {'color': "rgba(0,0,0,0)", 'thickness': 0},
                        'bgcolor': "#e9ecef",
                        'steps': [
                            {'range': [0, val_step_l], 'color': "#004a99"},
                            {'range': [val_step_l, val_gauge_l], 'color': "#dc3545"}
                        ],
                        'threshold': {'line': {'color': "black", 'width': 3}, 'thickness': 0.75, 'value': 100 if l_ven > 0 else 0}
                    }
                ))
                fig_l.update_layout(height=200, margin=dict(l=20, r=20, t=20, b=10))
                
                st.plotly_chart(fig_l, use_container_width=True, config={'displayModeBar': False}, key=f"gauge_linha_{idx}")
                st.markdown(f"""
                <div style='text-align: center; font-size: 12px; margin-top: -15px; margin-bottom: 20px;'>
                    <span style='color:#004a99; font-weight:bold;'>■ Prod: {perc_prod_int_l:.1f}%</span> 
                    &nbsp; 
                    <span style='color:#dc3545; font-weight:bold;'>■ Perdas: {perc_perd_int_l:.1f}%</span>
                </div>
                """, unsafe_allow_html=True)
                
            idx += 1
    else:
        st.info("Não há horas cadastradas e consumidas por linha de produção para este projeto específico.")

    st.markdown("---")

    st.markdown("### 🚨 Análise de Custo: Impacto de Horas Extras no Orçamento")
    
    col_proj_he1, col_proj_he2 = st.columns([1, 2])
    
    with col_proj_he1:
        st.write(f"**Composição de Horas do Projeto Selecionado**")
        df_he_so_micro = pd.read_sql_query("""
            SELECT SUM(horas_normais) as normais, SUM(he_50) as he50, SUM(he_100) as he100 
            FROM apontamentos 
            WHERE so=%(so)s AND tipo IN ('Produção Normal', 'Retrabalho', 'Parada')
        """, engine, params={"so": so_dash_clean})
        
        if not df_he_so_micro.empty and (df_he_so_micro['normais'][0] or df_he_so_micro['he50'][0] or df_he_so_micro['he100'][0]):
            v_norm = df_he_so_micro['normais'].iloc[0] or 0.0
            v_he50 = df_he_so_micro['he50'].iloc[0] or 0.0
            v_he100 = df_he_so_micro['he100'].iloc[0] or 0.0
            
            fig_pie_he = px.pie(names=['Horas Normais', 'Hora Extra 50%', 'Hora Extra 100%'], 
                                values=[v_norm, v_he50, v_he100],
                                color_discrete_sequence=['#004a99', '#17a2b8', '#fd7e14'],
                                hole=0.5)
            fig_pie_he.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20),
                                     legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5))
            st.plotly_chart(fig_pie_he, use_container_width=True, key="pie_he_proj_micro")
        else:
            st.info("Sem apontamentos para compor o custo deste projeto.")

    with col_proj_he2:
        st.write(f"**Comparativo de Horas Extras por Projetos Ativos (Geral)**")
        df_he_macro = pd.read_sql_query("""
            SELECT a.so, 
                   SUM(a.horas_normais) as normais, 
                   SUM(a.he_50) as he50, 
                   SUM(a.he_100) as he100
            FROM apontamentos a
            WHERE a.so != 'N/A' AND EXISTS (
                SELECT 1 FROM projetos p 
                WHERE p.so = a.so 
                AND (UPPER(TRIM(p.status_producao)) != 'FINALIZADO' OR p.status_producao IS NULL)
            )
            GROUP BY a.so
            HAVING (SUM(a.horas_normais) + SUM(a.he_50) + SUM(a.he_100)) > 0
        """, engine)
        
        if not df_he_macro.empty:
            df_he_macro['Total'] = df_he_macro['normais'] + df_he_macro['he50'] + df_he_macro['he100']
            df_he_macro = df_he_macro.sort_values(by='Total', ascending=False).head(10)
            
            fig_bar_he = go.Figure()
            fig_bar_he.add_trace(go.Bar(x=df_he_macro['so'], y=df_he_macro['normais'], name='Horas Normais', marker_color='#004a99'))
            fig_bar_he.add_trace(go.Bar(x=df_he_macro['so'], y=df_he_macro['he50'], name='HE 50%', marker_color='#17a2b8'))
            fig_bar_he.add_trace(go.Bar(x=df_he_macro['so'], y=df_he_macro['he100'], name='HE 100%', marker_color='#fd7e14'))
            
            fig_bar_he.update_layout(barmode='stack', height=350, margin=dict(l=20, r=20, t=20, b=20),
                                     legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
            st.plotly_chart(fig_bar_he, use_container_width=True, key="bar_he_proj_macro")
        else:
            st.info("Nenhum projeto ativo com apontamentos para analisar.")

    st.markdown("---")
    st.markdown("### 📑 Extrato Detalhado do Projeto (Kardex de Horas)")
    st.write("Auditoria completa: Verifique quem apontou, quando, qual a WO e se houve apontamento de perdas/retrabalhos.")

    with st.expander(f"Ver / Exportar Histórico de Apontamentos - {so_dash_sel}", expanded=False):
        df_kardex = pd.read_sql_query("""
            SELECT data_registro, operador, wo, unidade, atividade, tipo, tipo_erro, causador_erro,
                   (horas_normais + he_50 + he_100) AS res_h, descricao
            FROM apontamentos
            WHERE so = %(so)s
            ORDER BY SUBSTRING(data_registro FROM 7 FOR 4) || SUBSTRING(data_registro FROM 4 FOR 2) || SUBSTRING(data_registro FROM 1 FOR 2) DESC, hora_inicio DESC
        """, engine, params={"so": so_dash_clean})

        if not df_kardex.empty:
            cols_map_kardex = {
                'data_registro': 'Data',
                'operador': 'Operador',
                'wo': 'Work Order (WO)',
                'unidade': 'Unidade',
                'atividade': 'Atividade / Setor',
                'tipo': 'Tipo de Apontamento',
                'tipo_erro': 'Tipo de Erro',
                'causador_erro': 'Causador',
                'res_h': 'Total Horas (h)',
                'descricao': 'Observações'
            }
            df_kardex = df_kardex.rename(columns=cols_map_kardex)
            st.dataframe(df_kardex, use_container_width=True)

            output_kardex = io.BytesIO()
            with pd.ExcelWriter(output_kardex, engine='openpyxl') as writer:
                df_kardex.to_excel(writer, index=False, sheet_name='Kardex_Projeto')

            st.download_button(
                label=f"📥 Baixar Kardex em Excel (.xlsx)",
                data=output_kardex.getvalue(),
                file_name=f"Kardex_Projeto_{so_dash_clean}_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("Nenhum apontamento encontrado para este projeto.")


# ------------------------------------------
# ABA: DASHBOARD RH (RECURSOS HUMANOS)
# ------------------------------------------
with tab_dash_rh:
    if user_role == "viewer":
        st.error("🔒 Acesso Restrito - Modo de Visualização Gerencial (Apenas Leitura)")
    else:
        st.markdown("## 👥 Painel de Recursos Humanos")
        
        st.markdown("### 🏦 Passivo de Banco de Horas (Saldo Consolidado)")
        st.write("Visão financeira das horas: Negativo (Deve para a empresa) | Positivo (Crédito do funcionário).")
        
        df_bh_total = pd.read_sql_query("""
            SELECT a.operador, c.linha, SUM(a.saldo_bh) as saldo_total
            FROM apontamentos a
            JOIN colaboradores c ON a.matricula = c.matricula
            WHERE c.data_demissao IS NULL OR c.data_demissao = ''
            GROUP BY a.operador, c.linha
            ORDER BY saldo_total DESC
        """, engine)
        
        if not df_bh_total.empty:
            df_bh_total['cor'] = df_bh_total['saldo_total'].apply(lambda x: '#28a745' if x >= 0 else '#dc3545')
            
            fig_bh = go.Figure()
            fig_bh.add_trace(go.Bar(
                x=df_bh_total['operador'], 
                y=df_bh_total['saldo_total'], 
                marker_color=df_bh_total['cor'],
                text=df_bh_total['saldo_total'].round(2).astype(str) + "h",
                textposition='auto'
            ))
            fig_bh.update_layout(title="Saldo Histórico de Banco de Horas por Colaborador Ativo", yaxis_title="Horas (h)", height=350, margin=dict(t=40, b=10))
            st.plotly_chart(fig_bh, use_container_width=True, key="bar_banco_horas_rh")
        else:
            st.info("Não há saldo de banco de horas registrado.")
        
        st.markdown("---")
        
        st.markdown("### 🕒 Acompanhamento Diário de Ponto (Saldo de Horas)")
        
        df_lucy_check_rh = pd.read_sql_query("SELECT lucy_month, MIN(start_date) as start_date, MAX(end_date) as end_date FROM calendario_lucy GROUP BY lucy_month ORDER BY MIN(start_date) DESC", engine)
        
        if not df_lucy_check_rh.empty and df_lucy_check_rh['lucy_month'].iloc[0] is not None:
            meses_lucy = [f"{r['lucy_month']} (De {pd.to_datetime(r['start_date']).strftime('%d/%m/%Y')} a {pd.to_datetime(r['end_date']).strftime('%d/%m/%Y')})" for _, r in df_lucy_check_rh.iterrows()]
            mes_escolhido_rh = st.selectbox("Selecione o Mês Fiscal Lucy:", meses_lucy)
            idx_sel = meses_lucy.index(mes_escolhido_rh)
            data_ini_rh = pd.to_datetime(df_lucy_check_rh['start_date'].iloc[idx_sel]).date()
            data_fim_rh = pd.to_datetime(df_lucy_check_rh['end_date'].iloc[idx_sel]).date()
            titulo_mes = df_lucy_check_rh['lucy_month'].iloc[idx_sel]
        else:
            hoje_rh = datetime.now()
            data_ini_rh = hoje_rh.date().replace(day=1)
            _, num_days = calendar.monthrange(hoje_rh.year, hoje_rh.month)
            data_fim_rh = hoje_rh.date().replace(day=num_days)
            titulo_mes = data_ini_rh.strftime("%m/%Y")
            st.info("Sem calendário Lucy cadastrado. Usando mês civil atual.")

        if 'titulo_mes' in locals():
            st.write(f"Competência de Análise: **{titulo_mes}**")

        dias_mes = [data_ini_rh + timedelta(days=i) for i in range((data_fim_rh - data_ini_rh).days + 1)]
        
        cursor.execute("SELECT data FROM feriados")
        feriados_bd = [r[0] for r in cursor.fetchall()]
        
        df_colab_rh = pd.read_sql_query("SELECT matricula, nome, linha, data_admissao, data_demissao FROM colaboradores", engine)
        df_ferias_rh = pd.read_sql_query("SELECT matricula, data_inicio, data_fim FROM ferias_colaboradores", engine)
        
        df_ap_all = pd.read_sql_query("SELECT operador, data_registro, tipo, atividade, horas_normais, he_50, he_100, saldo_bh FROM apontamentos", engine)
        df_ap_all['data_dt'] = pd.to_datetime(df_ap_all['data_registro'], format='%d/%m/%Y', errors='coerce')
        df_ap_rh = df_ap_all[(df_ap_all['data_dt'].dt.date >= data_ini_rh) & (df_ap_all['data_dt'].dt.date <= data_fim_rh)].copy()
        
        df_ap_rh['total_horas'] = df_ap_rh['horas_normais'] + df_ap_rh['he_50'] + df_ap_rh['he_100'] + df_ap_rh['saldo_bh'].abs()
        
        apont_dict = {}
        for _, r in df_ap_rh.groupby(['operador', 'data_registro'])['total_horas'].sum().reset_index().iterrows():
            apont_dict[(r['operador'], r['data_registro'])] = r['total_horas']
            
        tabela_ponto = []
        dados_carga_rh = []
        
        for _, colab in df_colab_rh.iterrows():
            d_adm = pd.to_datetime(colab['data_admissao'], format='%Y-%m-%d', errors='coerce').date() if pd.notna(colab['data_admissao']) and str(colab['data_admissao']).strip() != '' else date.min
            d_dem = pd.to_datetime(colab['data_demissao'], format='%Y-%m-%d', errors='coerce').date() if pd.notna(colab['data_demissao']) and str(colab['data_demissao']).strip() != '' else date.max
            
            if d_adm > data_fim_rh or d_dem < data_ini_rh:
                continue

            linha_ponto = {'Operador': colab['nome']}
            mat = colab['matricula']
            cap_mensal_operador = 0.0
            
            for d in dias_mes:
                d_str_br_curto = d.strftime("%d/%m")
                d_str_iso = d.strftime("%Y-%m-%d")
                d_str_br_full = d.strftime("%d/%m/%Y")
                
                if d < d_adm or d > d_dem:
                    linha_ponto[d_str_br_curto] = "-"
                    continue
                
                em_ferias = False
                filtro_ferias = df_ferias_rh[df_ferias_rh['matricula'] == mat]
                for _, vf in filtro_ferias.iterrows():
                    try:
                        if pd.to_datetime(vf['data_inicio']).date() <= d <= pd.to_datetime(vf['data_fim']).date():
                            em_ferias = True
                            break
                    except: pass
                    
                is_feriado = d_str_iso in feriados_bd or d.weekday() == 6
                
                if em_ferias or is_feriado:
                    meta = 0.0
                else:
                    c_sq, c_sx, _, _ = obter_parametros_dia(conn, d)
                    if d.weekday() <= 3: meta = c_sq
                    elif d.weekday() == 4: meta = c_sx
                    else: meta = 0.0
                    
                cap_mensal_operador += meta
                
                apontado = apont_dict.get((colab['nome'], d_str_br_full), 0.0)
                saldo = apontado - meta
                linha_ponto[d_str_br_curto] = round(saldo, 2)
                
            tabela_ponto.append(linha_ponto)
            dados_carga_rh.append({'operador': colab['nome'], 'capacidade': cap_mensal_operador})
            
        df_ponto_final = pd.DataFrame(tabela_ponto)
        
        if not df_ponto_final.empty:
            df_ponto_final.set_index('Operador', inplace=True)
            try:
                styled_df = df_ponto_final.style.map(color_ponto, subset=[d.strftime("%d/%m") for d in dias_mes if d.strftime("%d/%m") in df_ponto_final.columns])
            except AttributeError:
                styled_df = df_ponto_final.style.applymap(color_ponto, subset=[d.strftime("%d/%m") for d in dias_mes if d.strftime("%d/%m") in df_ponto_final.columns])
            st.dataframe(styled_df, use_container_width=True)

        st.markdown("---")

        st.markdown("### 📊 Análise de Capacidade vs Apontamento")
        st.write("A barra verde ao fundo representa a disponibilidade do colaborador. As colunas coloridas representam o que foi apontado.")
        
        df_carga = pd.DataFrame(dados_carga_rh)
        
        if not df_ap_rh.empty and not df_carga.empty:
            def calc_normais(r):
                val = r['horas_normais'] if r['tipo'] in ['Produção Normal', 'Retrabalho'] else 0
                if val == 0 and r['tipo'] in ['Produção Normal', 'Retrabalho'] and pd.notna(r['saldo_bh']) and r['saldo_bh'] > 0:
                    val = r['saldo_bh']
                return val

            def calc_bh(r):
                if r['tipo'] in ['Falta/Atraso', 'Atestado / Justificada'] and pd.notna(r['atividade']) and 'Banco de Horas' in str(r['atividade']):
                    if r['horas_normais'] > 0:
                        return r['horas_normais']
                    elif pd.notna(r['saldo_bh']) and r['saldo_bh'] < 0:
                        return abs(r['saldo_bh'])
                return 0

            df_ap_rh['h_normais'] = df_ap_rh.apply(calc_normais, axis=1)
            df_ap_rh['paradas'] = df_ap_rh.apply(lambda r: r['horas_normais'] if r['tipo'] == 'Parada' else 0, axis=1)
            df_ap_rh['atestados'] = df_ap_rh.apply(lambda r: r['horas_normais'] if r['tipo'] in ['Atestado / Justificada', 'Falta/Atraso'] and ('Banco de Horas' not in str(r['atividade'])) else 0, axis=1)
            df_ap_rh['banco_horas'] = df_ap_rh.apply(calc_bh, axis=1)
            df_ap_rh['he50'] = df_ap_rh['he_50']
            df_ap_rh['he100'] = df_ap_rh['he_100']
            
            df_consumo_op = df_ap_rh.groupby('operador')[['h_normais', 'paradas', 'atestados', 'banco_horas', 'he50', 'he100']].sum().reset_index()
            df_consumo_op['total_apontado'] = df_consumo_op[['h_normais', 'paradas', 'atestados', 'banco_horas', 'he50', 'he100']].sum(axis=1)
            
            df_plot_carga = pd.merge(df_carga, df_consumo_op, on='operador', how='left').fillna(0)
            df_plot_carga = df_plot_carga.sort_values(by='total_apontado', ascending=False)
            
            base_paradas = df_plot_carga['h_normais']
            base_atestados = base_paradas + df_plot_carga['paradas']
            base_bh = base_atestados + df_plot_carga['atestados']
            base_he50 = base_bh + df_plot_carga['banco_horas']
            base_he100 = base_he50 + df_plot_carga['he50']
            
            tot_cap = df_plot_carga['capacidade'].sum()
            tot_hn = df_plot_carga['h_normais'].sum()
            tot_par = df_plot_carga['paradas'].sum()
            tot_ate = df_plot_carga['atestados'].sum()
            tot_bh = df_plot_carga['banco_horas'].sum()
            tot_he50 = df_plot_carga['he50'].sum()
            tot_he100 = df_plot_carga['he100'].sum()
            
            fig_carga = go.Figure()
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['capacidade'], name=f'Disponibilidade Mensal ({tot_cap:.1f}h)', marker_color='#28a745', offsetgroup=0))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['h_normais'], name=f'Normais/Trabalhadas ({tot_hn:.1f}h)', marker_color='#004a99', offsetgroup=1, base=0))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['paradas'], name=f'Paradas ({tot_par:.1f}h)', marker_color='#ffc107', offsetgroup=1, base=base_paradas))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['atestados'], name=f'Atestados/Faltas ({tot_ate:.1f}h)', marker_color='#dc3545', offsetgroup=1, base=base_atestados))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['banco_horas'], name=f'Banco de Horas ({tot_bh:.1f}h)', marker_color='#6cb2eb', offsetgroup=1, base=base_bh))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['he50'], name=f'HE 50% ({tot_he50:.1f}h)', marker_color='#fd7e14', offsetgroup=1, base=base_he50))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['he100'], name=f'HE 100% ({tot_he100:.1f}h)', marker_color='#d9480f', offsetgroup=1, base=base_he100))
            
            fig_carga.update_layout(barmode='group', height=450, margin=dict(l=20, r=20, t=30, b=20),
                                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
            st.plotly_chart(fig_carga, use_container_width=True, key="bar_carga_rh")
        else:
            st.info("Sem dados para a visão de capacidade.")

        st.markdown("---")
        
        col_rh_bot1, col_rh_bot2 = st.columns(2)
        
        with col_rh_bot1:
            st.markdown("### 🤒 Absenteísmo da Fábrica")
            
            df_abs = pd.merge(df_ap_rh, df_colab_rh[['nome', 'linha']], left_on='operador', right_on='nome', how='left')
            
            if not df_abs.empty:
                linhas_disp = ["- Todas as Linhas -"] + df_abs['linha'].dropna().unique().tolist()
                linha_sel = st.selectbox("Filtro por Setor/Linha:", linhas_disp, key="sb_linha_rh_abs")
                
                if linha_sel != "- Todas as Linhas -":
                    df_abs = df_abs[df_abs['linha'] == linha_sel]
                
                df_abs['is_ausencia'] = df_abs.apply(lambda r: r['tipo'] in ['Falta/Atraso', 'Atestado / Justificada'] and r['atividade'] != 'Banco de Horas', axis=1)
                total_ausencia = df_abs[df_abs['is_ausencia']]['horas_normais'].sum()
                total_geral = df_abs['horas_normais'].sum()
                
                taxa_geral = (total_ausencia / total_geral * 100) if total_geral > 0 else 0.0
                
                if total_geral > 0:
                    fig_pie = px.pie(names=['Horas Trabalhadas (Inc. BH)', 'Horas Ausentes'], 
                                    values=[max(0, total_geral - total_ausencia), total_ausencia],
                                    title=f"Taxa de Absenteísmo Real: {taxa_geral:.1f}%",
                                    color_discrete_sequence=['#28a745', '#dc3545'])
                    fig_pie.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
                    st.plotly_chart(fig_pie, use_container_width=True, key="pie_abs_rh")
                else:
                    st.info("Sem horas apontadas para este filtro.")
            else:
                st.info("Sem dados de absenteísmo.")

        with col_rh_bot2:
            st.markdown("### 🔍 Raio-X Individual do Colaborador")
            if not df_ap_rh.empty:
                ops_lista = sorted(df_ap_rh['operador'].unique())
                op_sel = st.selectbox("Selecione o Colaborador:", ops_lista)
                
                df_op_ind = df_ap_rh[df_ap_rh['operador'] == op_sel]
                h_norm = df_op_ind.apply(lambda r: r['horas_normais'] if r['tipo'] in ['Produção Normal', 'Retrabalho'] else 0, axis=1).sum()
                h_par = df_op_ind.apply(lambda r: r['horas_normais'] if r['tipo'] == 'Parada' else 0, axis=1).sum()
                
                h_ates = df_op_ind.apply(lambda r: r['horas_normais'] if r['tipo'] in ['Atestado / Justificada', 'Falta/Atraso'] and r['atividade'] != 'Banco de Horas' else 0, axis=1).sum()
                h_bh = df_op_ind.apply(lambda r: r['horas_normais'] if r['tipo'] == 'Falta/Atraso' and r['atividade'] == 'Banco de Horas' else 0, axis=1).sum()
                
                h_he50 = df_op_ind['he_50'].sum()
                h_he100 = df_op_ind['he_100'].sum()
                
                if (h_norm + h_par + h_ates + h_bh + h_he50 + h_he100) > 0:
                    df_pie_ind = pd.DataFrame({
                        'Métrica': ['Horas Normais', 'Banco de Horas', 'Atestados/Faltas', 'Paradas', 'HE 50%', 'HE 100%'],
                        'Horas': [h_norm, h_bh, h_ates, h_par, h_he50, h_he100]
                    })
                    fig_ind = px.pie(
                        df_pie_ind,
                        names='Métrica',
                        values='Horas',
                        hole=0.4,
                        title=f"Composição de Horas: {op_sel}",
                        color='Métrica',
                        color_discrete_map={
                            'Horas Normais': '#004a99',     
                            'Banco de Horas': '#6cb2eb',    
                            'Atestados/Faltas': '#dc3545',  
                            'Paradas': '#ffc107',           
                            'HE 50%': '#fd7e14',            
                            'HE 100%': '#d9480f'            
                        }
                    )
                    fig_ind.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20),
                                          legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5))
                    st.plotly_chart(fig_ind, use_container_width=True, key="pie_ind_rh")
                else:
                    st.info("Colaborador não tem apontamentos suficientes neste mês.")
            else:
                st.info("Sem dados para análise individual.")

# ------------------------------------------
# ABA: ORDENS DE PRODUÇÃO
# ------------------------------------------
with tab_ordens:
    if user_role == "viewer":
        st.error("🔒 Acesso Restrito - Modo de Visualização Gerencial (Apenas Leitura)")
    else:
        st.markdown("## 📋 Gestão de Ordens de Produção")
        col_ord1, col_ord2 = st.columns(2)
        
        with col_ord1:
            with st.expander("➕ Cadastrar Nova SO/WO", expanded=True):
                linhas_disponiveis = pd.read_sql_query("SELECT DISTINCT linha FROM colaboradores WHERE linha IS NOT NULL AND linha != ''", engine)['linha'].tolist()
                
                with st.form("form_nova_wo", clear_on_submit=True):
                    so_n = st.text_input("Sales Order (SO)*")
                    wo_n = st.text_input("Work Order (WO)*")
                    item_n = st.text_input("Item*") 
                    linha_n = st.selectbox("Linha de Produção Predominante*", ["- Selecione -"] + linhas_disponiveis)
                    cli_n = st.text_input("Cliente*")
                    prod_n = st.text_input("Nome do Produto*")
                    
                    qtd_n = st.number_input("Quantidade*", min_value=1, step=1)
                    hr_ven = st.number_input("Horas Vendidas*", min_value=0.0, step=0.5, value=0.0)
                    
                    if st.form_submit_button("💾 Criar Ordem", type="primary", use_container_width=False):
                        if not so_n or not wo_n or not item_n or not cli_n or not prod_n or linha_n == "- Selecione -" or hr_ven <= 0:
                            st.error("❌ Preencha os campos obrigatórios (*). As Horas Vendidas devem ser maiores que zero.")
                        else:
                            cursor.execute("""
                                INSERT INTO projetos (so, wo, linha, customer, item, product_name, qtde, status_producao, horas_vendidas) 
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """, (so_n.strip(), wo_n.strip(), linha_n, cli_n.strip(), item_n.strip(), prod_n.strip(), qtd_n, "Não iniciada", hr_ven))
                            conn.commit()
                            st.success("✔️ Ordem de Produção registrada!")
                            st.rerun()

        with col_ord2:
            with st.expander("✏️ Gerenciar / Atualizar Ordem", expanded=True):
                df_status_edit = pd.read_sql_query("SELECT so, wo, customer, item, product_name, qtde, horas_vendidas, status_producao FROM projetos WHERE UPPER(TRIM(status_producao)) != 'FINALIZADO' OR status_producao IS NULL", engine)
                
                if not df_status_edit.empty:
                    df_sos_ativas = df_status_edit[['so', 'customer']].drop_duplicates()
                    lista_sos_edit = ["- Selecione -"] + sorted([f"{r['so']} - {r['customer'] if pd.notna(r['customer']) else 'Desconhecido'}" for _, r in df_sos_ativas.iterrows()])
                    so_edit_sel = st.selectbox("1. Selecione o Projeto (SO):", lista_sos_edit, key="so_edit_status")
                    
                    if so_edit_sel != "- Selecione -":
                        so_clean = str(so_edit_sel.split(" - ")[0]).strip()
                        df_wos_ativas = df_status_edit[df_status_edit['so'].astype(str).str.strip() == so_clean]
                        
                        lista_wos_edit = ["- Selecione -"] + [f"{r['wo']} - {r['product_name'] if pd.notna(r['product_name']) else 'Desconhecido'}" for _, r in df_wos_ativas.iterrows()]
                        wo_edit_sel = st.selectbox("2. Selecione a Ordem (WO):", lista_wos_edit, key="wo_edit_status")
                        
                        if wo_edit_sel != "- Selecione -":
                            wo_clean_edit = str(wo_edit_sel.split(" - ")[0]).strip()
                            
                            filtro_wo = df_wos_ativas[df_wos_ativas['wo'].astype(str).str.strip() == wo_clean_edit]
                            
                            if not filtro_wo.empty:
                                row_wo = filtro_wo.iloc[0]
                                
                                st.markdown("---")
                                st.write("**Atualizar Dados da Ordem**")
                                novo_wo = st.text_input("Work Order (WO)", value=row_wo['wo'])
                                novo_item = st.text_input("Item", value=row_wo['item'])
                                novo_nome = st.text_input("Produto", value=row_wo['product_name'])
                                
                                c_ed1, c_ed2, c_ed3 = st.columns(3)
                                nova_qtd = c_ed1.number_input("Quantidade", value=int(row_wo['qtde']) if pd.notna(row_wo['qtde']) else 1, min_value=1, step=1)
                                novas_hr = c_ed2.number_input("Horas Vendidas", value=float(row_wo['horas_vendidas']) if pd.notna(row_wo['horas_vendidas']) else 0.0, min_value=0.0, step=0.5)
                                novo_st = c_ed3.selectbox("Status", ["Não iniciada", "Em Montagem", "Finalizado", "Parado (Material)", "Reserva Estratégica"], index=["Não iniciada", "Em Montagem", "Finalizado", "Parado (Material)", "Reserva Estratégica"].index(row_wo['status_producao']) if row_wo['status_producao'] in ["Não iniciada", "Em Montagem", "Finalizado", "Parado (Material)", "Reserva Estratégica"] else 0)
                                
                                c_btn1, c_btn2 = st.columns([3, 1])
                                
                                if c_btn1.button("💾 Atualizar Dados", type="primary", use_container_width=False):
                                    if not novo_wo.strip() or not novo_nome.strip():
                                        st.error("A WO e o Produto não podem ficar em branco.")
                                    else:
                                        cursor.execute("UPDATE projetos SET wo=%s, item=%s, product_name=%s, qtde=%s, horas_vendidas=%s, status_producao=%s WHERE so=%s AND wo=%s", 
                                                       (novo_wo.strip(), novo_item.strip(), novo_nome.strip(), nova_qtd, novas_hr, novo_st, so_clean, wo_clean_edit))
                                        
                                        if novo_wo.strip() != wo_clean_edit:
                                            cursor.execute("UPDATE planejamento SET wo=%s WHERE so=%s AND wo=%s", (novo_wo.strip(), so_clean, wo_clean_edit))
                                            cursor.execute("UPDATE apontamentos SET wo=%s, product_name=%s WHERE so=%s AND wo=%s", (novo_wo.strip(), novo_nome.strip(), so_clean, wo_clean_edit))
                                            
                                        conn.commit()
                                        st.success("✔️ Ordem e vínculos atualizados com sucesso!")
                                        time_sys.sleep(1.5)
                                        st.rerun()
                                        
                                if c_btn2.button("🗑️ Excluir Ordem", use_container_width=False):
                                    cursor.execute("DELETE FROM projetos WHERE so=%s AND wo=%s", (so_clean, wo_clean_edit))
                                    cursor.execute("DELETE FROM planejamento WHERE so=%s AND wo=%s", (so_clean, wo_clean_edit))
                                    conn.commit()
                                    st.success("Ordem excluída da base de dados!")
                                    time_sys.sleep(1.5)
                                    st.rerun()
                            else:
                                st.error("❌ Ordem não encontrada para edição. O formato do dado pode estar incompatível no banco.")
                else:
                    st.info("Nenhuma ordem ativa encontrada.")

        st.markdown("### 📊 Ordens Registradas")
        st.dataframe(pd.read_sql_query("SELECT so, wo, item, linha, customer, product_name, qtde, horas_vendidas, status_producao FROM projetos", engine), use_container_width=True, height=400)


# ------------------------------------------
# ABA: PLANEJAMENTO E ALOCAÇÃO 
# ------------------------------------------
with tab_plan:
    st.markdown("## 📅 Planejamento de Carga de Máquina e Operador")
    
    if user_role != "viewer":
        col_plan1, col_plan2 = st.columns(2)
        with col_plan1:
            with st.container(border=True):
                st.markdown("### ➕ Planejamento Reverso (MRP Preditivo)")
                
                df_wo_ativas = pd.read_sql_query("SELECT so, wo, linha, customer, product_name, qtde, horas_vendidas FROM projetos WHERE UPPER(TRIM(status_producao)) != 'FINALIZADO' OR status_producao IS NULL", engine)
                df_planejados = pd.read_sql_query("SELECT DISTINCT wo FROM planejamento", engine)
                wos_planejadas = df_planejados['wo'].tolist()
                
                df_pendentes = df_wo_ativas[~df_wo_ativas['wo'].isin(wos_planejadas)]
                
                if df_pendentes.empty:
                    st.info("🎉 Todas as Ordens de Produção ativas já possuem planejamento!")
                else:
                    df_so_cust = df_pendentes[['so', 'customer']].drop_duplicates()
                    lista_so_plan = ["- Selecione -"] + sorted([f"{r['so']} - {r['customer'] if pd.notna(r['customer']) else 'Desconhecido'}" for _, r in df_so_cust.iterrows()])
                    so_sel_full = st.selectbox("1. Selecione o Projeto (SO)", lista_so_plan, key="so_sel_mrp")
                    
                    if so_sel_full != "- Selecione -":
                        so_sel_plan = so_sel_full.split(" - ")[0].strip()
                        df_wo_filtradas = df_pendentes[df_pendentes['so'] == so_sel_plan]
                        lista_wos = ["- Selecione -"] + [f"{r['wo']} - {r['product_name'] if pd.notna(r['product_name']) else 'Desconhecido'}" for _, r in df_wo_filtradas.iterrows()]
                        
                        wo_sel_full = st.selectbox("2. Ordem de Produção (WO Sem Planejamento)", lista_wos, key="wo_sel_mrp_wo")
                        
                        if wo_sel_full != "- Selecione -":
                            wo_clean = str(wo_sel_full.split(" - ")[0]).strip()
                            filtro_wo_plan = df_wo_filtradas[df_wo_filtradas['wo'].astype(str).str.strip() == wo_clean]
                            
                            if not filtro_wo_plan.empty:
                                wo_data = filtro_wo_plan.iloc[0]
                                st.info(f"⚙️ **Linha:** {wo_data['linha']} | 👤 **Cliente:** {wo_data['customer']}")
                                
                                qtde_wo = int(wo_data['qtde']) if pd.notna(wo_data['qtde']) else 1
                                lista_unidades_plan = ["Geral"] + [f"Unidade {i}" for i in range(1, qtde_wo + 1)] if qtde_wo > 0 else ["Geral"]
                                unidade_plan_sel = st.selectbox("3. Unidade a Planejar", lista_unidades_plan)
                                
                                horas_bd = float(wo_data['horas_vendidas']) if pd.notna(wo_data['horas_vendidas']) and wo_data['horas_vendidas'] > 0 else 8.0
                                horas_base = st.number_input("4. Horas Estimadas (Base)", min_value=0.5, step=0.5, value=horas_bd)
                                fator_seguranca = st.slider("5. Fator de Segurança (%)", min_value=0, max_value=50, value=10, step=5)
                                
                                horas_totais_com_fator = round(horas_base * (1 + (fator_seguranca / 100.0)), 2)
                                st.markdown(f"Horas Totais a Alocar (com margem): <span style='color:#004a99; font-weight:bold; font-size:18px;'>{horas_totais_com_fator}h</span>", unsafe_allow_html=True)
                                
                                linha_wo = wo_data['linha']
                                if linha_wo and str(linha_wo) != "None" and str(linha_wo).strip() != "":
                                    df_colab_plan = pd.read_sql_query("SELECT matricula, nome FROM colaboradores WHERE (data_demissao IS NULL OR data_demissao = '') AND linha = %(linha)s", engine, params={"linha": linha_wo})
                                else:
                                    df_colab_plan = pd.read_sql_query("SELECT matricula, nome FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''", engine)
                                
                                if df_colab_plan.empty:
                                    st.warning(f"Nenhum colaborador encontrado para a linha '{linha_wo}'.")
                                    lista_ops = []
                                else:
                                    lista_ops = [f"{r['matricula']} - {r['nome']}" for _, r in df_colab_plan.iterrows()]
                                
                                ops_selecionados = st.multiselect("5. Operador(es)", lista_ops)
                                
                                data_entrega = st.date_input("6. Data de Entrega (Deadline)", date.today() + timedelta(days=7), format="DD/MM/YYYY")
    
                                alerta_duplicidade = False
                                ja_planejado = pd.read_sql_query("SELECT DISTINCT c.nome FROM planejamento p JOIN colaboradores c ON p.matricula = c.matricula WHERE p.wo = %(wo)s AND p.unidade = %(und)s", engine, params={"wo": wo_clean, "und": unidade_plan_sel})
                                if not ja_planejado.empty:
                                    nomes_ja = ", ".join(ja_planejado['nome'].tolist())
                                    st.warning(f"⚠️ Atenção: A {unidade_plan_sel} desta WO já possui planejamento para: {nomes_ja}. Utilize o Replanejamento ao lado para limpar antes de prosseguir se desejar refazer.")
                                    alerta_duplicidade = True
                                    
                                if st.button("💾 Executar Planejamento Reverso", type="primary", use_container_width=False):
                                    if not ops_selecionados:
                                        st.error("❌ Selecione pelo menos um operador.")
                                    elif alerta_duplicidade:
                                        st.error("❌ Limpe o planejamento antigo desta WO/Unidade antes de refazer a alocação.")
                                    else:
                                        so_plan = so_sel_plan
                                        horas_por_op = horas_totais_com_fator / len(ops_selecionados)
                                        
                                        alocacoes_temp = []
                                        datas_protegidas_alerta = []
                                        
                                        for op in ops_selecionados:
                                            mat_plan = op.split(" - ")[0]
                                            nome_op = op.split(" - ")[1]
                                            horas_restantes = horas_por_op
                                            data_atual_loop = data_entrega
                                            
                                            loop_seguro = 0 
                                            while horas_restantes > 0.01 and loop_seguro < 365:
                                                loop_seguro += 1
                                                
                                                data_iso_loop = data_atual_loop.strftime("%Y-%m-%d")
                                                data_br_loop = data_atual_loop.strftime("%d/%m/%Y")
                                                
                                                cursor.execute("SELECT 1 FROM feriados WHERE data = %s", (data_iso_loop,))
                                                is_100 = cursor.fetchone() or data_atual_loop.weekday() >= 5
                                                
                                                cursor.execute("SELECT 1 FROM ferias_colaboradores WHERE matricula = %s AND %s BETWEEN data_inicio AND data_fim", (mat_plan, data_iso_loop))
                                                em_ferias = cursor.fetchone()
                                                
                                                if is_100 or em_ferias: 
                                                    data_atual_loop -= timedelta(days=1) 
                                                    continue
                                                
                                                cursor.execute("SELECT SUM(horas_normais) FROM apontamentos WHERE matricula = %s AND data_registro = %s AND tipo IN ('Atestado / Justificada', 'Falta/Atraso')", (mat_plan, data_br_loop))
                                                res = cursor.fetchone()
                                                ausencia_agendada = float(res[0]) if res and res[0] else 0.0
                                                
                                                cursor.execute("SELECT COUNT(*) FROM planejamento WHERE matricula = %s AND data_planejada = %s AND wo != %s", (mat_plan, data_iso_loop, wo_clean))
                                                ja_ocupado_dia = cursor.fetchone()[0]
                                                
                                                if ja_ocupado_dia > 0:
                                                    datas_protegidas_alerta.append(f"{nome_op} ({data_br_loop})")
                                                    data_atual_loop -= timedelta(days=1)
                                                    continue
                                                    
                                                c_sq, c_sx, _, _ = obter_parametros_dia(conn, data_atual_loop)
                                                cap_dia = c_sq if data_atual_loop.weekday() <= 3 else c_sx
                                                
                                                cap_dia -= ausencia_agendada
                                                
                                                if cap_dia <= 0.05:
                                                    data_atual_loop -= timedelta(days=1) 
                                                    continue
                                                
                                                cursor.execute("SELECT SUM(horas_planejadas) FROM planejamento WHERE matricula = %s AND data_planejada = %s AND wo = %s", (mat_plan, data_iso_loop, wo_clean))
                                                res_ja_plan = cursor.fetchone()
                                                ja_plan_mesmo_projeto = float(res_ja_plan[0]) if res_ja_plan and res_ja_plan[0] else 0.0
                                                
                                                cap_disponivel = cap_dia - ja_plan_mesmo_projeto
                                                
                                                if cap_disponivel <= 0:
                                                    data_atual_loop -= timedelta(days=1) 
                                                    continue
                                                    
                                                alocar_agora = min(cap_disponivel, horas_restantes)
                                                alocar_agora = round(alocar_agora, 2)
                                                
                                                alocacoes_temp.append((data_iso_loop, mat_plan, so_plan, wo_clean, unidade_plan_sel, alocar_agora))
                                                horas_restantes -= alocar_agora
                                                
                                                if horas_restantes > 0.01:
                                                    data_atual_loop -= timedelta(days=1) 
                                                    
                                        for aloc in alocacoes_temp:
                                            cursor.execute("INSERT INTO planejamento (data_planejada, matricula, so, wo, unidade, horas_planejadas) VALUES (%s,%s,%s,%s,%s,%s)", aloc)
                                        conn.commit()
                                        
                                        st.success("✔️ Planejamento Sequencial gravado com sucesso!")
                                        if datas_protegidas_alerta:
                                            st.info(f"⚠️ **Alerta de Proteção PCP:** O sistema realocou a produção desviando das datas já ocupadas ou com ausências médicas de: {', '.join(set(datas_protegidas_alerta))}")
                                        
                                        time_sys.sleep(2.0)
                                        st.rerun()
                            else:
                                st.error("❌ Ordem não encontrada na base de dados.")

        with col_plan2:
            with st.expander("🔄 Replanejamento / Limpar Alocação", expanded=True):
                wos_com_plano = pd.read_sql_query("""
                    SELECT DISTINCT pl.so, pl.wo, pl.unidade, p.product_name, p.customer
                    FROM planejamento pl
                    LEFT JOIN projetos p ON pl.wo = p.wo
                """, engine)
                
                if not wos_com_plano.empty:
                    df_so_cust_rep = wos_com_plano[['so', 'customer']].drop_duplicates()
                    lista_sos_replan = ["- Selecione -"] + sorted([f"{r['so']} - {r['customer'] if pd.notna(r['customer']) else 'Desconhecido'}" for _, r in df_so_cust_rep.iterrows()])
                    so_replan_full = st.selectbox("1. Selecione o Projeto (SO):", lista_sos_replan, key="so_replan_del")
                    
                    if so_replan_full != "- Selecione -":
                        so_replan = so_replan_full.split(" - ")[0].strip()
                        df_wos_replan = wos_com_plano[wos_com_plano['so'] == so_replan]
                        wos_list_formatada = ["- Selecione -"] + [f"{r['wo']} - {r['product_name'] if pd.notna(r['product_name']) else 'Desconhecido'} | Unidade: {r['unidade']}" for _, r in df_wos_replan.iterrows()]
                        
                        wo_und_replan = st.selectbox("2. Selecione a WO e Unidade para excluir:", wos_list_formatada, key="wo_und_replan")
                        
                        if wo_und_replan != "- Selecione -":
                            if st.button("🗑️ Excluir Cronograma do Período", use_container_width=False):
                                parte_esq, parte_dir = wo_und_replan.split(" | Unidade: ")
                                wo_excluir = parte_esq.split(" - ")[0].strip()
                                und_excluir = parte_dir.strip()
                                cursor.execute("DELETE FROM planejamento WHERE wo = %s AND unidade = %s", (wo_excluir, und_excluir))
                                conn.commit()
                                st.success("Planejamento excluído! A WO voltou para a lista de pendentes.")
                                time_sys.sleep(1.5)
                                st.rerun()
                else:
                    st.info("Não há nenhum cronograma ativo para limpar.")
        st.markdown("---")

    # A PARTIR DAQUI SÃO OS GRÁFICOS SOLICITADOS (RODAM LIVREMENTE EM MODOS ADMIN E VIEW)
    st.markdown("### 📊 Gráfico de Gantt do Chão de Fábrica (Visão Limpa por Projeto)")
    st.write("Linhas de montagem separadas por sombreamento cinza contínuo. Passe o mouse sobre as raias para ver o detalhamento completo.")
    
    df_lucy_gantt_check = pd.read_sql_query("SELECT lucy_month, MIN(start_date) as start_date, MAX(end_date) as end_date FROM calendario_lucy GROUP BY lucy_month ORDER BY MIN(start_date) DESC", engine)
    
    mes_escolhido = None
    data_ini_gantt, data_fim_gantt = None, None
    
    if not df_lucy_gantt_check.empty and df_lucy_gantt_check['lucy_month'].iloc[0] is not None:
        meses_gantt_list = [f"{r['lucy_month']} (De {pd.to_datetime(r['start_date']).strftime('%d/%m/%Y')} a {pd.to_datetime(r['end_date']).strftime('%d/%m/%Y')})" for _, r in df_lucy_gantt_check.iterrows()]
        col_fil_g1, col_fil_g2 = st.columns(2)
        with col_fil_g1:
            mes_gantt_sel = st.selectbox("Filtrar Período do Cronograma:", ["Ver Tudo"] + meses_gantt_list, key="sb_gantt_mes")
        
        if mes_gantt_sel != "Ver Tudo":
            idx_g = meses_gantt_list.index(mes_gantt_sel)
            data_ini_gantt = pd.to_datetime(df_lucy_gantt_check['start_date'].iloc[idx_g]).strftime("%Y-%m-%d")
            data_fim_gantt = pd.to_datetime(df_lucy_gantt_check['end_date'].iloc[idx_g]).strftime("%Y-%m-%d")
            query_gantt = f"""
                SELECT p.data_planejada, c.nome as operador, c.linha as linha, p.so, p.wo, p.unidade, p.horas_planejadas, pr.customer, pr.product_name 
                FROM planejamento p 
                LEFT JOIN colaboradores c ON p.matricula = c.matricula 
                LEFT JOIN projetos pr ON p.wo = pr.wo 
                WHERE p.data_planejada BETWEEN '{data_ini_gantt}' AND '{data_fim_gantt}'
            """
        else:
            data_ini_gantt = "2020-01-01"
            query_gantt = """
                SELECT p.data_planejada, c.nome as operador, c.linha as linha, p.so, p.wo, p.unidade, p.horas_planejadas, pr.customer, pr.product_name 
                FROM planejamento p 
                LEFT JOIN colaboradores c ON p.matricula = c.matricula 
                LEFT JOIN projetos pr ON p.wo = pr.wo
            """
    else:
        col_fil_g1, col_fil_g2 = st.columns(2)
        with col_fil_g1:
            mes_gantt_sel = st.date_input("Visualizar a partir de:", date.today(), key="dt_gantt_fallback")
        data_ini_gantt = mes_gantt_sel.strftime("%Y-%m-%d")
        query_gantt = f"""
            SELECT p.data_planejada, c.nome as operador, c.linha as linha, p.so, p.wo, p.unidade, p.horas_planejadas, pr.customer, pr.product_name 
            FROM planejamento p 
            LEFT JOIN colaboradores c ON p.matricula = c.matricula 
            LEFT JOIN projetos pr ON p.wo = pr.wo 
            WHERE p.data_planejada >= '{data_ini_gantt}'
        """
        
    df_gantt_raw = pd.read_sql_query(query_gantt, engine)
    
    ferias_rows = []
    ferias_df = pd.read_sql_query("SELECT f.matricula, c.nome as operador, c.linha, f.data_inicio, f.data_fim FROM ferias_colaboradores f JOIN colaboradores c ON f.matricula = c.matricula", engine)
    for _, r in ferias_df.iterrows():
        try:
            start = pd.to_datetime(r['data_inicio'])
            end = pd.to_datetime(r['data_fim'])
            for n in range(int((end - start).days) + 1):
                dt = (start + timedelta(days=n)).strftime("%Y-%m-%d")
                ferias_rows.append({'data_planejada': dt, 'operador': r['operador'], 'linha': r['linha'], 'so': '⏸️ AFASTAMENTO', 'wo': '🏖️ FÉRIAS', 'unidade': '-', 'horas_planejadas': 8.0, 'customer': '-', 'product_name': '-'})
        except: pass

    ausencias_df = pd.read_sql_query("SELECT a.data_registro, a.operador, c.linha, a.tipo, a.atividade, a.horas_normais FROM apontamentos a JOIN colaboradores c ON a.matricula = c.matricula WHERE a.tipo IN ('Atestado / Justificada', 'Falta/Atraso')", engine)
    ausencia_rows = []
    for _, r in ausencias_df.iterrows():
        try:
            dt = pd.to_datetime(r['data_registro'], format="%d/%m/%Y").strftime("%Y-%m-%d")
            wo_text = "🕒 Banco de Horas" if r['atividade'] == 'Banco de Horas' else f"⚕️ {r['atividade']}"
            ausencia_rows.append({'data_planejada': dt, 'operador': r['operador'], 'linha': r['linha'], 'so': '⏸️ AFASTAMENTO', 'wo': wo_text, 'unidade': '-', 'horas_planejadas': r['horas_normais'], 'customer': '-', 'product_name': '-'})
        except: pass

    if ferias_rows or ausencia_rows:
        df_extras = pd.DataFrame(ferias_rows + ausencia_rows)
        if 'data_fim_gantt' in locals() and data_fim_gantt:
            df_extras = df_extras[(df_extras['data_planejada'] >= data_ini_gantt) & (df_extras['data_planejada'] <= data_fim_gantt)]
        else:
            df_extras = df_extras[df_extras['data_planejada'] >= data_ini_gantt]
        df_gantt_raw = pd.concat([df_gantt_raw, df_extras], ignore_index=True)
    
    with col_fil_g2:
        if not df_gantt_raw.empty:
            df_valid_sos = df_gantt_raw[df_gantt_raw['so'] != '⏸️ AFASTAMENTO'][['so', 'customer']].drop_duplicates()
            lista_isolamento = ["- Mostrar Todos os Projetos (Fábrica) -"] + sorted([f"{r['so']} - {r['customer'] if pd.notna(r['customer']) else 'Desconhecido'}" for _, r in df_valid_sos.iterrows()])
            
            so_iso_sel = st.selectbox("🔍 Isolar Caminho de um Projeto (SO):", lista_isolamento)
            if so_iso_sel != "- Mostrar Todos os Projetos (Fábrica) -":
                so_clean_iso = so_iso_sel.split(" - ")[0].strip()
                df_gantt_raw = df_gantt_raw[(df_gantt_raw['so'] == so_clean_iso) | (df_gantt_raw['so'] == '⏸️ AFASTAMENTO')]
        else:
            st.selectbox("🔍 Isolar Caminho de um Projeto (SO):", ["- Sem Planejamentos Ativos -"], disabled=True)
            
    if not df_gantt_raw.empty:
        df_overlap = df_gantt_raw.groupby(['operador', 'data_planejada']).size().reset_index(name='count')
        ops_sobrepostos = df_overlap[df_overlap['count'] > 1]['operador'].unique()
        if len(ops_sobrepostos) > 0:
            nomes_alerta = [op.split()[0] for op in ops_sobrepostos]
            st.warning(f"⚠️ Atenção: Detectamos choque de agenda para {', '.join(set(nomes_alerta))}. Há mais de uma ordem planejada para o mesmo dia, as barras aparecerão sobrepostas para indicar o conflito.")

        df_gantt_raw['Primeiro_Nome'] = df_gantt_raw['operador'].apply(lambda x: str(x).split()[0] if pd.notna(x) else "")
        df_gantt_raw['data_dt'] = pd.to_datetime(df_gantt_raw['data_planejada'])
        df_gantt_raw['linha'] = df_gantt_raw['linha'].fillna("Sem Setor Cadastrado")
        
        df_gant = df_gantt_raw.groupby(['operador', 'Primeiro_Nome', 'linha', 'so', 'wo', 'unidade']).agg(
            start_date=('data_dt', 'min'),
            end_date=('data_dt', 'max'),
            total_horas=('horas_planejadas', 'sum')
        ).reset_index()
        
        df_gant['start_date'] = pd.to_datetime(df_gant['start_date']).dt.normalize()
        df_gant['Fim'] = pd.to_datetime(df_gant['end_date']).dt.normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)
        
        df_gant['Data Inicio BR'] = df_gant['start_date'].dt.strftime('%d/%m/%Y')
        df_gant['Data Fim BR'] = df_gant['end_date'].dt.strftime('%d/%m/%Y')
        df_gant['Identificacao'] = df_gant['so'] + " [" + df_gant['unidade'] + "]"
        
        df_gant = df_gant.sort_values(by=['linha', 'operador', 'start_date']).reset_index(drop=True)
        
        lanes = {}
        lane_assignments = []
        for i, row in df_gant.iterrows():
            op = row['operador']
            start = row['start_date']
            
            if op not in lanes:
                lanes[op] = []
            
            assigned_lane = 0
            lane_found = False
            for l_idx, end_date in enumerate(lanes[op]):
                if start > end_date: 
                    assigned_lane = l_idx
                    lanes[op][l_idx] = row['Fim']
                    lane_found = True
                    break
                    
            if not lane_found:
                assigned_lane = len(lanes[op])
                lanes[op].append(row['Fim'])
                
            lane_assignments.append(assigned_lane)

        df_gant['lane'] = lane_assignments
        df_gant['Eixo_Y_Unico'] = df_gant['operador'] + df_gant['lane'].apply(lambda x: '\u200b' * x)

        cursor.execute("SELECT DISTINCT so FROM projetos")
        todas_sos = [r[0] for r in cursor.fetchall() if r[0]]
        cursor.execute("SELECT DISTINCT so FROM planejamento")
        todas_sos += [r[0] for r in cursor.fetchall() if r[0]]
        todas_sos = sorted(list(set(todas_sos)))
        
        color_discrete_map = {so: px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)] for i, so in enumerate(todas_sos)}
        color_discrete_map['⏸️ AFASTAMENTO'] = '#6c757d' 

        fig_gantt_final = px.timeline(
            df_gant, x_start="start_date", x_end="Fim", y="Eixo_Y_Unico", color="so",
            hover_name="Identificacao", title="Gantt Avançado Lucy Group (Com Sub-Raias de Conflito)",
            custom_data=['Data Inicio BR', 'Data Fim BR', 'total_horas', 'linha', 'wo'],
            color_discrete_map=color_discrete_map
        )
        
        fig_gantt_final.update_traces(
            hovertemplate="<b>%{hovertext}</b><br><br>Setor: %{customdata[3]}<br>WO: %{customdata[4]}<br>Prazo: %{customdata[0]} até %{customdata[1]}<br>Carga de Trabalho: %{customdata[2]:.2f}h Período<extra></extra>",
            marker_line_color='rgb(8,48,107)', marker_line_width=1.5, opacity=0.9
        )
        
        ordered_raias = list(df_gant['Eixo_Y_Unico'].unique())[::-1] 
        ticktexts = []
        for raia in ordered_raias:
            if not raia.endswith('\u200b'):
                row_info = df_gant[df_gant['Eixo_Y_Unico'] == raia].iloc[0]
                ticktexts.append(f"[{row_info['linha']}] {row_info['Primeiro_Nome']}")
            else:
                ticktexts.append("")

        fig_gantt_final.update_yaxes(categoryorder="array", categoryarray=ordered_raias, tickvals=ordered_raias, ticktext=ticktexts, title="")
        
        fig_gantt_final.update_xaxes(title="Período Cronograma (Dias)")
        
        fig_gantt_final.update_layout(
            legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5, title="Identificação de Cores por Projeto"),
            height=max(450, len(ordered_raias) * 42),
            width=1400, 
            margin=dict(l=10, r=20, t=40, b=80)
        )
        
        unique_setores = df_gant['linha'].unique()
        tons_cinza = ["#ffffff", "#f1f3f5", "#e9ecef", "#dee2e6", "#ced4da"]
        
        op_to_idx = {op: i for i, op in enumerate(ordered_raias)}
        
        for k, set_nome in enumerate(unique_setores):
            fatiamento_setor = df_gant[df_gant['linha'] == set_nome]
            raias_do_setor = fatiamento_setor['Eixo_Y_Unico'].unique()
            
            if len(raias_do_setor) > 0:
                idxs = [op_to_idx[op] for op in raias_do_setor if op in op_to_idx]
                if idxs:
                    min_idx = min(idxs)
                    max_idx = max(idxs)
                    cor_bloco = tons_cinza[k % len(tons_cinza)]
                    
                    fig_gantt_final.add_hrect(
                        y0=min_idx - 0.5, y1=max_idx + 0.5, 
                        fillcolor=cor_bloco, opacity=1.0, layer="below", line_width=0
                    )
                    
                    mid_lane = ordered_raias[int((min_idx + max_idx) / 2)]
                    fig_gantt_final.add_annotation(
                        x=0.005, xref="paper", xanchor="left", y=mid_lane, yref="y",
                        text=f"🏢 <b>{set_nome}</b>", showarrow=False,
                        font=dict(size=13, color="#004a99"), bgcolor="rgba(255,255,255,0.85)", borderpad=4
                    )
                
        st.plotly_chart(fig_gantt_final, width='content', config={'scrollZoom': True}, key="chart_gantt_mes_lucy")
        
        with st.expander("Ver Tabela Estruturada de Alocação"):
            df_export = df_gantt_raw[df_gantt_raw['so'] != '⏸️ AFASTAMENTO'].copy()
            df_export = padronizar_datas_para_tela(df_export, ['data_planejada'])
            
            cols_map = {
                'data_planejada': 'Data Planejada',
                'linha': 'Linha de Produção',
                'operador': 'Operador',
                'so': 'Sales Order (SO)',
                'customer': 'Cliente',
                'wo': 'Work Order (WO)',
                'product_name': 'Produto',
                'unidade': 'Unidade',
                'horas_planejadas': 'Horas Planejadas'
            }
            
            df_export = df_export[[c for c in cols_map.keys() if c in df_export.columns]].rename(columns=cols_map)
            df_export = df_export.sort_values(by=['Data Planejada', 'Linha de Produção', 'Operador'])
            
            st.dataframe(df_export, use_container_width=True)
            
            output_plan = io.BytesIO()
            with pd.ExcelWriter(output_plan, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Cronograma_PCP')
                
            st.download_button(
                label="📥 Baixar Tabela em Excel (.xlsx)", 
                data=output_plan.getvalue(), 
                file_name=f"Cronograma_PCP_{date.today().strftime('%Y%m%d')}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
        st.markdown("---")
        
        # ⚖️ BALANÇO DE CAPACIDADE VS DEMANDA
        st.markdown("### ⚖️ Balanço de Capacidade vs. Demanda (Ocupação do Período)")
        st.write("Visão estratégica para tomada de decisão: Aprovação de Horas Extras vs. Liberação de Banco de Horas.")
        
        if 'data_ini_gantt' in locals() and data_ini_gantt:
            dt_start_cap = pd.to_datetime(data_ini_gantt).date()
            if 'data_fim_gantt' in locals() and data_fim_gantt:
                dt_end_cap = pd.to_datetime(data_fim_gantt).date()
            else:
                dt_end_cap = dt_start_cap + timedelta(days=30)
                
            date_list_cap = [dt_start_cap + timedelta(days=x) for x in range((dt_end_cap - dt_start_cap).days + 1)]
            
            df_colabs_ativos_bal = pd.read_sql_query("SELECT matricula, nome, linha, data_admissao, data_demissao FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''", engine)
            df_ferias_bal = pd.read_sql_query("SELECT matricula, data_inicio, data_fim FROM ferias_colaboradores", engine)
            
            cursor.execute("SELECT data FROM feriados")
            feriados_bd_bal = [r[0] for r in cursor.fetchall()]
            
            cap_linha = {}
            cap_total_fabrica = 0.0
            
            for _, colab in df_colabs_ativos_bal.iterrows():
                linha_op = colab['linha'] if pd.notna(colab['linha']) and colab['linha'].strip() != '' else 'Sem Setor'
                if linha_op not in cap_linha: cap_linha[linha_op] = 0.0
                
                mat = colab['matricula']
                d_adm = pd.to_datetime(colab['data_admissao'], format='%Y-%m-%d', errors='coerce').date() if pd.notna(colab['data_admissao']) and str(colab['data_admissao']).strip() != '' else date.min
                
                for d in date_list_cap:
                    if d < d_adm: continue
                    is_feriado = d.strftime("%Y-%m-%d") in feriados_bd_bal or d.weekday() == 6
                    em_ferias = False
                    filtro_f = df_ferias_bal[df_ferias_bal['matricula'] == mat]
                    for _, vf in filtro_f.iterrows():
                        try:
                            if pd.to_datetime(vf['data_inicio']).date() <= d <= pd.to_datetime(vf['data_fim']).date():
                                em_ferias = True
                                break
                        except: pass
                    if not (is_feriado or em_ferias):
                        c_sq, c_sx, _, _ = obter_parametros_dia(conn, d)
                        if d.weekday() <= 3: 
                            cap_linha[linha_op] += c_sq
                            cap_total_fabrica += c_sq
                        elif d.weekday() == 4: 
                            cap_linha[linha_op] += c_sx
                            cap_total_fabrica += c_sx

            if not df_gantt_raw.empty:
                df_plan_clean = df_gantt_raw[df_gantt_raw['so'] != '⏸️ AFASTAMENTO']
                df_plan_agrupado = df_plan_clean.groupby('linha')['horas_planejadas'].sum().reset_index()
                total_plan_fabrica = df_plan_clean['horas_planejadas'].sum()
            else:
                df_plan_agrupado = pd.DataFrame(columns=['linha', 'horas_planejadas'])
                total_plan_fabrica = 0.0
                
            df_capacidade = pd.DataFrame(list(cap_linha.items()), columns=['linha', 'capacidade_h'])
            df_balanco = pd.merge(df_capacidade, df_plan_agrupado, on='linha', how='left').fillna(0)
            
            df_balanco['ocupacao_pct'] = ((df_balanco['horas_planejadas'] / df_balanco['capacidade_h']) * 100).fillna(0)
            df_balanco['saldo_h'] = df_balanco['capacidade_h'] - df_balanco['horas_planejadas']
            
            ocup_global_pct = (total_plan_fabrica / cap_total_fabrica * 100) if cap_total_fabrica > 0 else 0
            saldo_global = cap_total_fabrica - total_plan_fabrica
            
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Capacidade Total", f"{cap_total_fabrica:.0f}h")
            col_m2.metric("Horas Planejadas", f"{total_plan_fabrica:.0f}h")
            col_m3.metric("Saldo Livre (Ociosidade)", f"{saldo_global:.0f}h", delta=f"{saldo_global:.0f}h", delta_color="normal" if saldo_global >= 0 else "inverse")
            col_m4.metric("Ocupação Global", f"{ocup_global_pct:.1f}%")
            
            df_balanco = df_balanco.sort_values('ocupacao_pct', ascending=False)
            fig_bal = go.Figure()
            fig_bal.add_trace(go.Bar(x=df_balanco['linha'], y=df_balanco['capacidade_h'], name='Capacidade Disponível', marker_color='#28a745'))
            fig_bal.add_trace(go.Bar(x=df_balanco['linha'], y=df_balanco['horas_planejadas'], name='Demanda Planejada', marker_color='#004a99'))
            
            fig_bal.update_layout(barmode='group', title="Gargalos e Ociosidade por Setor", yaxis_title="Horas", height=350, margin=dict(t=30, b=10))
            st.plotly_chart(fig_bal, use_container_width=True, key="bar_balanco_capacidade")
            
        else:
            st.info("Selecione um período no filtro do Gantt para visualizar o balanço de capacidade.")

        st.markdown("---")
        
        # 🎯 QUADRO DE ADERÊNCIA OPERACIONAL
        st.markdown("### 🎯 Quadro de Aderência Operacional: Capacidade vs Planejado vs Realizado")
        st.write("Visão consolidada cruzando a meta de carga do sistema com os apontamentos reais de produção na fábrica.")
        
        if 'data_ini_gantt' in locals() and data_ini_gantt:
            if 'data_fim_gantt' in locals() and data_fim_gantt:
                df_plan_rel = pd.read_sql_query(f"SELECT data_planejada, matricula, wo, unidade, horas_planejadas FROM planejamento WHERE data_planejada BETWEEN '{data_ini_gantt}' AND '{data_fim_gantt}'", engine)
            else:
                df_plan_rel = pd.read_sql_query(f"SELECT data_planejada, matricula, wo, unidade, horas_planejadas FROM planejamento WHERE data_planejada >= '{data_ini_gantt}'", engine)
        else:
            df_plan_rel = pd.read_sql_query("SELECT data_planejada, matricula, wo, unidade, horas_planejadas FROM planejamento", engine)
            
        df_apont_rel = pd.read_sql_query("SELECT data_registro, matricula, operador, wo, unidade, horas_normais as horas_realizadas FROM apontamentos WHERE tipo = 'Produção Normal'", engine)
        
        if not df_plan_rel.empty:
            df_plan_rel = df_plan_rel.rename(columns={'data_planejada': 'data_iso'})
            if not df_apont_rel.empty:
                df_apont_rel['data_iso'] = pd.to_datetime(df_apont_rel['data_registro'], format="%d/%m/%Y", errors='coerce').dt.strftime('%Y-%m-%d')
                
                if 'data_fim_gantt' in locals() and data_fim_gantt and 'data_ini_gantt' in locals() and data_ini_gantt:
                    df_apont_rel = df_apont_rel[(df_apont_rel['data_iso'] >= data_ini_gantt) & (df_apont_rel['data_iso'] <= data_fim_gantt)]
                elif 'data_ini_gantt' in locals() and data_ini_gantt:
                    df_apont_rel = df_apont_rel[df_apont_rel['data_iso'] >= data_ini_gantt]
                    
                df_apont_agrup = df_apont_rel.groupby(['data_iso', 'matricula', 'wo', 'unidade'])['horas_realizadas'].sum().reset_index()
            else:
                df_apont_agrup = pd.DataFrame(columns=['data_iso', 'matricula', 'wo', 'unidade', 'horas_realizadas'])
                
            df_aderencia = pd.merge(df_plan_rel, df_apont_agrup, on=['data_iso', 'matricula', 'wo', 'unidade'], how='outer')
            df_aderencia['horas_planejadas'] = df_aderencia['horas_planejadas'].fillna(0)
            df_aderencia['horas_realizadas'] = df_aderencia['horas_realizadas'].fillna(0)
            
            df_colabs_info = pd.read_sql_query("SELECT matricula, nome, linha, data_admissao, data_demissao FROM colaboradores", engine)
            df_active_colabs = df_colabs_info[(df_colabs_info['data_demissao'].isna()) | (df_colabs_info['data_demissao'] == '')]
            
            df_aderencia = pd.merge(df_aderencia, df_active_colabs, on='matricula', how='inner')
            
            if not df_aderencia.empty:
                if 'data_ini_gantt' in locals() and data_ini_gantt and 'data_fim_gantt' in locals() and data_fim_gantt:
                    dt_start = pd.to_datetime(data_ini_gantt).date()
                    dt_end = pd.to_datetime(data_fim_gantt).date()
                else:
                    dt_start = pd.to_datetime(df_aderencia['data_iso'].min()).date()
                    dt_end = pd.to_datetime(df_aderencia['data_iso'].max()).date()
                
                date_list = [dt_start + timedelta(days=x) for x in range((dt_end - dt_start).days + 1)]
                
                cursor.execute("SELECT data FROM feriados")
                feriados_bd = [r[0] for r in cursor.fetchall()]
                
                df_ferias_rh = pd.read_sql_query("SELECT matricula, data_inicio, data_fim FROM ferias_colaboradores", engine)
                
                cap_dict = {}
                for _, colab in df_active_colabs.iterrows():
                    mat = colab['matricula']
                    d_adm = pd.to_datetime(colab['data_admissao'], format='%Y-%m-%d', errors='coerce').date() if pd.notna(colab['data_admissao']) and str(colab['data_admissao']).strip() != '' else date.min
                    
                    cap_total = 0.0
                    for d in date_list:
                        if d < d_adm: continue
                        is_feriado = d.strftime("%Y-%m-%d") in feriados_bd or d.weekday() == 6
                        em_ferias = False
                        filtro_f = df_ferias_rh[df_ferias_rh['matricula'] == mat]
                        for _, vf in filtro_f.iterrows():
                            try:
                                if pd.to_datetime(vf['data_inicio']).date() <= d <= pd.to_datetime(vf['data_fim']).date():
                                    em_ferias = True
                                    break
                            except: pass
                        if not (is_feriado or em_ferias):
                            c_sq, c_sx, _, _ = obter_parametros_dia(conn, d)
                            if d.weekday() <= 3: cap_total += c_sq
                            elif d.weekday() == 4: cap_total += c_sx
                    cap_dict[colab['nome']] = cap_total
                
                df_ad_grafico = df_aderencia.groupby(['linha', 'nome'])[['horas_planejadas', 'horas_realizadas']].sum().reset_index()
                df_ad_grafico = df_ad_grafico.sort_values(by=['linha', 'nome'])
                
                df_ad_grafico['P_Nome'] = df_ad_grafico['nome'].apply(lambda x: str(x).split()[0] if pd.notna(x) else "N/A")
                df_ad_grafico['Exibicao_X'] = "[" + df_ad_grafico['linha'] + "] " + df_ad_grafico['P_Nome']
                df_ad_grafico['capacidade'] = df_ad_grafico['nome'].map(cap_dict).fillna(0)
                
                fig_ad = go.Figure()
                fig_ad.add_trace(go.Bar(x=df_ad_grafico['Exibicao_X'], y=df_ad_grafico['horas_planejadas'], name='Horas Planejadas', marker_color='#ffc107'))
                fig_ad.add_trace(go.Bar(x=df_ad_grafico['Exibicao_X'], y=df_ad_grafico['horas_realizadas'], name='Horas Realizadas', marker_color='#004a99'))
                fig_ad.add_trace(go.Scatter(x=df_ad_grafico['Exibicao_X'], y=df_ad_grafico['capacidade'], name='Capacidade (Teto)', mode='lines+markers', line=dict(color='#28a745', width=3), marker=dict(size=8)))
                
                fig_ad.update_layout(barmode='group', title="Cumprimento de Metas de Carga por Operador Ativo",
                                     xaxis_title="", yaxis_title="Horas Operacionais",
                                     height=380, margin=dict(t=30, b=10),
                                     legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
                st.plotly_chart(fig_ad, use_container_width=True, key="bar_aderencia_plan_final")
                
                with st.expander("Ver Tabela Detalhada Diária (Aderência)"):
                    df_aderencia['Desvio (h)'] = df_aderencia['horas_realizadas'] - df_aderencia['horas_planejadas']
                    st.dataframe(df_aderencia[['data_iso', 'nome', 'linha', 'wo', 'unidade', 'horas_planejadas', 'horas_realizadas', 'Desvio (h)']], use_container_width=True)
            else:
                st.info("Nenhum dado de planejamento ou apontamento para colaboradores ativos neste período.")
        else:
            st.info("Nenhum planejamento registrado para a escala selecionada.")


# ------------------------------------------
# ABA: MANUTENÇÃO E IMPORTAÇÃO
# ------------------------------------------
with tab_manutencao:
    if user_role == "viewer":
        st.error("🔒 Acesso Restrito - Modo de Visualização Gerencial (Apenas Leitura)")
    else:
        st.subheader("⚙️ Manutenção de Dados Mestre")
        
        cat_manut = st.radio("Selecione a Tabela de Visualização/Edição:", [
            "Colaboradores", "Férias", "Feriados", 
            "Calendário Lucy", "Configurações (Erros e Paradas)", "Parâmetros de Jornada", 
            "📥 Importação de Excel (Em Lote)"
        ], horizontal=True)
        
        with st.container(border=True):
            if cat_manut == "📥 Importação de Excel (Em Lote)":
                st.subheader("📤 Importação via Excel")
                op_c = st.selectbox("Qual tabela deseja atualizar via Excel?", ["WOs/SOs", "Colaboradores", "Férias", "Calendário Lucy", "Feriados", "Tipos de Erro", "Causadores de Erro"])
                
                guias = {
                    "WOs/SOs": ["so", "customer", "wo", "item", "product_name", "qtde", "horas_vendidas", "linha"],
                    "Colaboradores": ["matricula", "nome", "linha", "data_admissao", "data_demissao"],
                    "Férias": ["matricula", "data_inicio", "data_fim"],
                    "Calendário Lucy": ["start_date", "end_date", "std_month", "lucy_month", "week"],
                    "Feriados": ["data", "descricao"],
                    "Tipos de Erro": ["erro"],
                    "Causadores de Erro": ["causador"]
                }
                
                colunas_de_data = {
                    "Colaboradores": ["data_admissao", "data_demissao"],
                    "Férias": ["data_inicio", "data_fim"],
                    "Calendário Lucy": ["start_date", "end_date"],
                    "Feriados": ["data"]
                }
                
                st.markdown(f"""
                <div style="background-color: #e8f0fe; padding: 15px; border-radius: 10px; border-left: 5px solid #004a99; margin-bottom: 20px;">
                    <p style="margin:0;"><b>Colunas Requeridas no Excel (1ª Linha):</b><br>
                    <code>{" | ".join(guias[op_c])}</code></p>
                </div>
                """, unsafe_allow_html=True)
                
                f_xlsx = st.file_uploader("Selecione a Planilha (.xlsx)", type=["xlsx"])
                if f_xlsx and st.button("🚀 EXECUTAR IMPORTAÇÃO", use_container_width=True):
                    try:
                        df_up = pd.read_excel(f_xlsx)
                        df_up.columns = guias[op_c]
                        
                        if op_c in colunas_de_data:
                            df_up = formatar_datas_para_banco(df_up, colunas_de_data[op_c])
                        
                        target = {
                            "WOs/SOs": ("projetos", True), "Colaboradores": ("colaboradores", False), 
                            "Férias": ("ferias_colaboradores", False), "Calendário Lucy": ("calendario_lucy", False),
                            "Feriados": ("feriados", False), "Tipos de Erro": ("tipos_erro", False),
                            "Causadores de Erro": ("causadores_erro", False)
                        }
                        
                        t_name, has_status = target[op_c]
                        if has_status: df_up['status_producao'] = 'Não iniciada'
                        if op_c == "WOs/SOs": df_up['item'] = ""
                        
                        df_up.to_sql(t_name, engine, if_exists='append', index=False)
                        st.success(f"✔️ Carga de '{op_c}' concluída com sucesso no banco de dados!")
                    except Exception as e:
                        st.error(f"❌ Erro na importação. Verifique se as colunas estão corretas. Detalhe técnico: {e}")

            elif cat_manut == "Parâmetros de Jornada":
                st.write("**Histórico de Vigências de Jornada**")
                df_param = pd.read_sql_query("SELECT * FROM parametros_jornada ORDER BY data_inicio DESC", engine)
                df_param = padronizar_datas_para_tela(df_param, ['data_inicio', 'data_fim'])
                st.dataframe(df_param, use_container_width=True)
                
                st.markdown("---")
                st.write("**Cadastrar Nova Regra de Jornada**")
                st.caption("Atenção: Ao cadastrar uma nova regra, a anterior será encerrada um dia antes da data de início selecionada.")
                with st.form("form_nova_jornada"):
                    c1, c2, c3 = st.columns(3)
                    d_ini_n = c1.date_input("Válido a partir de (Início da Nova Regra):", date.today() + timedelta(days=1), format="DD/MM/YYYY")
                    h_sq_n = c2.time_input("Hora de Saída (Seg-Qui)", time(17,5))
                    c_sq_n = c2.number_input("Carga Horária-Relógio (Seg-Qui)", value=8.17, step=0.01)
                    h_sx_n = c3.time_input("Hora de Saída (Sexta)", time(15,0))
                    c_sx_n = c3.number_input("Carga Horária-Relógio (Sexta)", value=6.25, step=0.01)
                    
                    if st.form_submit_button("💾 Aplicar e Salvar Nova Vigência"):
                        data_iso_nova = d_ini_n.strftime("%Y-%m-%d")
                        cursor.execute("UPDATE parametros_jornada SET data_fim = TO_CHAR(%s::DATE - INTERVAL '1 day', 'YYYY-MM-DD') WHERE data_fim IS NULL", (data_iso_nova,))
                        cursor.execute("INSERT INTO parametros_jornada (data_inicio, carga_seg_qui, carga_sexta, hora_saida_seg_qui, hora_saida_sexta) VALUES (%s,%s,%s,%s,%s)", 
                                       (data_iso_nova, c_sq_n, c_sx_n, h_sq_n.strftime("%H:%M"), h_sx_n.strftime("%H:%M")))
                        conn.commit()
                        st.success("✔️ Nova regra de jornada e horário de saída aplicada com sucesso!")
                        st.rerun()

            elif cat_manut == "Colaboradores":
                c_col1, c_col2 = st.columns([1, 2])
                with c_col1:
                    st.write("**Registrar Desligamento**")
                    colab_ativos = pd.read_sql_query("SELECT matricula, nome FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''", engine)
                    if not colab_ativos.empty:
                        mat_dem = st.selectbox("Selecione o Colaborador:", [f"{r['matricula']} - {r['nome']}" for _, r in colab_ativos.iterrows()])
                        d_dem = st.date_input("Data de Desligamento", date.today(), format="DD/MM/YYYY")
                        if st.button("💾 Registrar Desligamento", use_container_width=True):
                            cursor.execute("UPDATE colaboradores SET data_demissao = %s WHERE matricula = %s", (d_dem.strftime("%Y-%m-%d"), mat_dem.split(" - ")[0]))
                            conn.commit()
                            st.success("Desligamento registrado!"); st.rerun()
                    else:
                        st.info("Não há colaboradores ativos para desligar.")
                with c_col2:
                    st.write("**Lista Geral de Colaboradores**")
                    df_colab_view = pd.read_sql_query("SELECT * FROM colaboradores", engine)
                    df_colab_view = padronizar_datas_para_tela(df_colab_view, ['data_admissao', 'data_demissao'])
                    st.dataframe(df_colab_view, use_container_width=True)
            
            elif cat_manut == "Férias":
                c_f1, c_f2 = st.columns([1, 2])
                with c_f1:
                    st.write("**Lançar Férias**")
                    colab_df = pd.read_sql_query("SELECT matricula, nome FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''", engine)
                    mat_f = st.selectbox("Colaborador:", [f"{r['matricula']} - {r['nome']}" for _, r in colab_df.iterrows()])
                    d_ini = st.date_input("Data de Início", date.today(), format="DD/MM/YYYY")
                    d_fim = st.date_input("Data de Fim", date.today() + timedelta(days=30), format="DD/MM/YYYY")
                    if st.button("💾 Salvar Período", use_container_width=True):
                        cursor.execute("INSERT INTO ferias_colaboradores (matricula, data_inicio, data_fim) VALUES (%s,%s,%s)", (mat_f.split(" - ")[0], d_ini.strftime("%Y-%m-%d"), d_fim.strftime("%Y-%m-%d")))
                        conn.commit(); st.success("Férias registradas!"); st.rerun()
                with c_f2:
                    st.write("**Períodos Cadastrados**")
                    df_ferias_view = pd.read_sql_query("SELECT * FROM ferias_colaboradores", engine)
                    df_ferias_view = padronizar_datas_para_tela(df_ferias_view, ['data_inicio', 'data_fim'])
                    st.dataframe(df_ferias_view, use_container_width=True)
                    
            elif cat_manut == "Feriados":
                df_feriados_view = pd.read_sql_query("SELECT * FROM feriados", engine)
                df_feriados_view = padronizar_datas_para_tela(df_feriados_view, ['data'])
                st.dataframe(df_feriados_view, use_container_width=True)
                
            elif cat_manut == "Calendário Lucy":
                df_cal_view = pd.read_sql_query("SELECT * FROM calendario_lucy", engine)
                df_cal_view = padronizar_datas_para_tela(df_cal_view, ['start_date', 'end_date'])
                st.dataframe(df_cal_view, use_container_width=True)
                
            elif cat_manut == "Configurações (Erros e Paradas)":
                cf1, cf2, cf3 = st.columns(3)
                with cf1:
                    st.write("**Categorias de Parada**")
                    add_p = st.text_input("Nova Parada:")
                    if st.button("Salvar Parada", use_container_width=True) and add_p:
                        cursor.execute("INSERT INTO categorias_parada (categoria) VALUES (%s) ON CONFLICT (categoria) DO NOTHING", (add_p,))
                        conn.commit(); st.rerun()
                    st.dataframe(pd.read_sql_query("SELECT * FROM categorias_parada", engine), use_container_width=True)
                with cf2:
                    st.write("**Tipos de Erro**")
                    add_e = st.text_input("Novo Erro:")
                    if st.button("Salvar Erro", use_container_width=True) and add_e:
                        cursor.execute("INSERT INTO tipos_erro (erro) VALUES (%s) ON CONFLICT (erro) DO NOTHING", (add_e,))
                        conn.commit(); st.rerun()
                    st.dataframe(pd.read_sql_query("SELECT * FROM tipos_erro", engine), use_container_width=True)
                with cf3:
                    st.write("**Causadores**")
                    add_c = st.text_input("Novo Causador:")
                    if st.button("Salvar Causador", use_container_width=True) and add_c:
                        cursor.execute("INSERT INTO causadores_erro (causador) VALUES (%s) ON CONFLICT (causador) DO NOTHING", (add_c,))
                        conn.commit(); st.rerun()
                    st.dataframe(pd.read_sql_query("SELECT * FROM causadores_erro", engine), use_container_width=True)

# ------------------------------------------
# ABA: RELATÓRIOS PDF 
# ------------------------------------------
with tab_pdf:
    if user_role == "viewer":
        st.error("🔒 Acesso Restrito - Modo de Visualização Gerencial (Apenas Leitura)")
    else:
        st.markdown("### 📄 Relatório Executivo de Retrabalhos e Paradas (PDF)")
        st.write("O sistema unificará automaticamente apontamentos fragmentados (mesma WO, operador e observação) em uma única ocorrência no relatório.")
        
        df_projetos_re = pd.read_sql_query("""
            SELECT DISTINCT a.so, p.customer 
            FROM apontamentos a
            LEFT JOIN projetos p ON a.so = p.so
            WHERE a.tipo IN ('Retrabalho', 'Parada') AND a.so != 'N/A'
        """, engine)
        
        if df_projetos_re.empty:
            st.info("Nenhum retrabalho ou parada vinculada a projeto registrada no sistema até o momento.")
        else:
            opcoes_so = []
            for _, r in df_projetos_re.iterrows():
                cliente = r['customer'] if pd.notna(r['customer']) else "Desconhecido"
                opcoes_so.append(f"{r['so']} - {cliente}")
                
            so_pdf_sel = st.selectbox("Selecione a Ordem de Venda (SO) para o Relatório:", list(dict.fromkeys(opcoes_so)))

            if st.button("⚙️ Processar e Gerar PDF", type="primary", use_container_width=True):
                try:
                    from fpdf import FPDF
                    
                    so_clean = so_pdf_sel.split(" - ")[0]
                    
                    query_sql = """
                    SELECT * FROM apontamentos 
                    WHERE so=%(so_clean)s AND tipo IN ('Retrabalho', 'Parada') 
                    """
                    df_ret = pd.read_sql_query(query_sql, engine, params={"so_clean": so_clean})
                    
                    if not df_ret.empty:
                        df_ret['data_dt'] = pd.to_datetime(df_ret['data_registro'], format='%d/%m/%Y')
                        df_ret = df_ret.fillna('N/A')
                        
                        df_ret['total_horas'] = df_ret['horas_normais'].astype(float) + df_ret['he_50'].astype(float) + df_ret['he_100'].astype(float)
                        
                        df_grouped = df_ret.groupby(
                            ['tipo', 'wo', 'operador', 'unidade', 'tipo_erro', 'causador_erro', 'atividade', 'descricao']
                        ).agg(
                            qtd_apontamentos=('id', 'count'),
                            primeiro_id=('id', 'first'),
                            total_horas=('total_horas', 'sum'),
                            data_min=('data_dt', 'min'),
                            data_max=('data_dt', 'max'),
                            foto_path=('foto_path', 'first'),
                            foto_depois_path=('foto_depois_path', 'first')
                        ).reset_index()
                        
                        df_grouped = df_grouped.sort_values(by=['data_min', 'tipo'])
                        
                        total_h_ret = round(df_grouped[df_grouped['tipo'] == 'Retrabalho']['total_horas'].sum(), 2)
                        total_h_parada = round(df_grouped[df_grouped['tipo'] == 'Parada']['total_horas'].sum(), 2)

                        class PDFReport(FPDF):
                            def header(self):
                                self.set_font("Arial", 'B', 12)
                                self.cell(0, 6, txt=limpa_texto_pdf("Relatorio de Perdas: Retrabalho e Paradas"), ln=True, align='C')
                                
                                self.set_font("Arial", 'B', 9)
                                self.cell(0, 5, txt=limpa_texto_pdf(f"Projeto (SO): {so_pdf_sel}"), ln=True, align='C')
                                
                                self.set_font("Arial", 'B', 9)
                                self.set_text_color(200, 0, 0)
                                self.cell(95, 5, txt=limpa_texto_pdf(f"Retrabalho: {total_h_ret}h"), align='R')
                                self.set_text_color(200, 100, 0)
                                self.cell(95, 5, txt=limpa_texto_pdf(f" | Paradas: {total_h_parada}h"), ln=True, align='L')
                                
                                self.set_text_color(0, 0, 0)
                                self.line(10, self.get_y()+1, 200, self.get_y()+1)
                                self.ln(4)

                            def footer(self):
                                self.set_y(-15)
                                self.set_font("Arial", 'I', 8)
                                self.cell(0, 10, f"Pagina {self.page_no()}", align='C')

                        pdf = PDFReport()
                        pdf.add_page()
                        
                        for idx, row in df_grouped.iterrows():
                            is_retrabalho = row['tipo'] == 'Retrabalho'
                            espaco_necessario = 115 if is_retrabalho else 40
                            
                            if pdf.get_y() + espaco_necessario > 280:
                                pdf.add_page()
                                
                            pdf.set_font("Arial", 'B', 11)
                            
                            id_text = f"#{row['primeiro_id']}"
                            if row['qtd_apontamentos'] > 1:
                                id_text += " (Agrupado)"
                                
                            d_min = row['data_min'].strftime('%d/%m/%Y')
                            d_max = row['data_max'].strftime('%d/%m/%Y')
                            str_data = d_min if d_min == d_max else f"{d_min} a {d_max}"
                            str_horas = f"{round(row['total_horas'], 2)}h"
                            
                            if is_retrabalho:
                                pdf.set_text_color(200, 0, 0)
                                pdf.cell(0, 6, txt=limpa_texto_pdf(f"[RETRABALHO] Ref. {id_text} | WO: {row['wo']} | Data: {str_data}"), ln=True)
                                pdf.set_text_color(0, 0, 0)
                                
                                pdf.set_font("Arial", '', 9)
                                pdf.cell(0, 5, txt=limpa_texto_pdf(f"Operador: {row['operador']} | Erro: {row['tipo_erro']} | Causador: {row['causador_erro']}"), ln=True)
                                pdf.cell(0, 5, txt=limpa_texto_pdf(f"Total de Horas Perdidas: {str_horas} | Unidade: {row['unidade']}"), ln=True)
                                pdf.multi_cell(0, 5, txt=limpa_texto_pdf(f"Observacao: {row['descricao']}"))
                                pdf.ln(2)

                                path_a = preparar_imagem_pdf(row['foto_path'])
                                path_d = preparar_imagem_pdf(row['foto_depois_path'])

                                if path_a:
                                    pdf.cell(90, 5, txt="Evidencia: ANTES", ln=False, align='C')
                                if path_d:
                                    pdf.cell(90, 5, txt="Evidencia: DEPOIS", ln=True, align='C')
                                elif path_a and not path_d:
                                    pdf.ln(5)
                                else:
                                    pdf.ln(5)

                                y_img = pdf.get_y()
                                altura_imagem = 64
                                has_img = False
                                
                                if path_a:
                                    try:
                                        pdf.image(path_a, x=15, y=y_img, w=85, h=altura_imagem)
                                        has_img = True
                                    except Exception:
                                        pdf.text(x=20, y=y_img + 30, txt="[Imagem ANTES Corrompida]")
                                        has_img = True
                                        
                                if path_d:
                                    try:
                                        pdf.image(path_d, x=110, y=y_img, w=85, h=altura_imagem)
                                        has_img = True
                                    except Exception:
                                        pdf.text(x=115, y=y_img + 30, txt="[Imagem DEPOIS Corrompida]")
                                        has_img = True

                                if has_img:
                                    pdf.set_y(y_img + altura_imagem + 5)
                                else:
                                    pdf.set_y(y_img + 2)
                                    
                            elif row['tipo'] == 'Parada':
                                pdf.set_text_color(200, 100, 0)
                                pdf.cell(0, 6, txt=limpa_texto_pdf(f"[PARADA] Ref. {id_text} | WO: {row['wo']} | Data: {str_data}"), ln=True)
                                pdf.set_text_color(0, 0, 0)
                                
                                pdf.set_font("Arial", '', 9)
                                pdf.cell(0, 5, txt=limpa_texto_pdf(f"Operador: {row['operador']} | Categoria: {row['atividade']}"), ln=True)
                                pdf.cell(0, 5, txt=limpa_texto_pdf(f"Total de Horas Paradas: {str_horas} | Unidade: {row['unidade']}"), ln=True)
                                pdf.multi_cell(0, 5, txt=limpa_texto_pdf(f"Motivo / Observacao: {row['descricao']}"))
                                pdf.ln(4)

                            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
                            pdf.ln(6)

                        try: pdf_bytes = pdf.output(dest='S').encode('latin-1')
                        except: pdf_bytes = bytes(pdf.output())

                        st.download_button(label="📥 Baixar PDF do Relatório", data=pdf_bytes, file_name=f"Relatorio_Perdas_SO_{so_clean}.pdf", mime="application/pdf", use_container_width=True)
                        st.success("✔️ Relatório Inteligente compilado com sucesso!")

                except ImportError:
                    st.error("❌ A biblioteca FPDF não está instalada. Abra o terminal e execute: pip install fpdf")
                except Exception as e:
                    st.error(f"❌ Ocorreu um erro técnico na geração do documento: {e}")

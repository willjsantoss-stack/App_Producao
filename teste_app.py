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
import requests
from io import BytesIO
from supabase import create_client, Client

# ==========================================
# 1. CONFIGURAÇÕES E DIRETÓRIOS
# ==========================================
st.set_page_config(page_title="LEBR - Production Management", page_icon="⚡", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(BASE_DIR, 'Logo_Lucy')
PASTA_FOTOS = os.path.join(BASE_DIR, "Fotos_Retrabalho")

for p in [LOGO_DIR, PASTA_FOTOS]:
    os.makedirs(p, exist_ok=True)

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

# ==========================================
# 2.1 CONEXÃO COM O SUPABASE STORAGE (FOTOS)
# ==========================================
url_supa = st.secrets["SUPABASE_URL"]
if url_supa.endswith("/rest/v1/"): 
    url_supa = url_supa.replace("/rest/v1/", "") # Limpa a URL automaticamente
    
key_supa = st.secrets["SUPABASE_KEY"]
supabase_client: Client = create_client(url_supa, key_supa)

# Função que empacota a criação das tabelas para não dar o NameError
# Função que empacota a criação das tabelas para não dar o NameError
def init_db():
    # ⚡ MÁGICA AQUI: Ativa o processamento isolado para o banco não travar!
    conn.autocommit = True 

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
    # 1. Configurações de Custos Globais (HH e OH)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parametros_custos (
            parametro TEXT PRIMARY KEY,
            valor NUMERIC
        )
    ''')
    cursor.execute("INSERT INTO parametros_custos (parametro, valor) VALUES ('taxa_hh', 77.17), ('taxa_oh', 1.7569) ON CONFLICT (parametro) DO NOTHING;")

    # 2. Itens Kanban Fixos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS itens_kanban (
            codigo TEXT PRIMARY KEY,
            descricao TEXT
        )
    ''')

    # 3. Matérias-Primas / Fáscias a Ignorar na Auditoria
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS itens_ignorados_auditoria (
            codigo TEXT PRIMARY KEY,
            descricao TEXT,
            motivo TEXT
        )
    ''')

    # 4. Histórico de Divergências de 3 Vias (Engenharia vs Fábrica)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auditoria_3vias_historico (
            id SERIAL PRIMARY KEY,
            data_auditoria TIMESTAMP,
            item TEXT,
            descricao TEXT,
            qtd_bom_inicial NUMERIC,
            qtd_bom_final NUMERIC,
            qtd_real NUMERIC,
            desvio_engenharia NUMERIC,
            desvio_fabrica NUMERIC,
            valor_impacto NUMERIC,
            status TEXT
        )
    ''')
    conn.commit()

    # Tabela de Causas Raízes (Motivos de Auditoria)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS motivos_auditoria (
            motivo TEXT PRIMARY KEY
        )
    ''')
    
    # Insere as opções padrão se a tabela estiver vazia
    cursor.execute("SELECT COUNT(*) FROM motivos_auditoria")
    if cursor.fetchone()[0] == 0:
        default_motivos = ["Scrap / Refugo", "Ajuste de Projeto (BOM)", "Quebra na Montagem", "Substituição de Material", "Perda de Processo", "Erro de Separação / Estoque"]
        for m in default_motivos:
            cursor.execute("INSERT INTO motivos_auditoria (motivo) VALUES (%s) ON CONFLICT (motivo) DO NOTHING", (m,))

    # 1. TABELA DE PROJETISTAS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projetistas (
            id SERIAL PRIMARY KEY,
            nome TEXT,
            especialidade TEXT
        )
    ''')
    
    # Pré-cadastrar a sua equipe automaticamente se a tabela estiver vazia
    cursor.execute("SELECT COUNT(*) FROM projetistas")
    if cursor.fetchone()[0] == 0:
        equipe = [
            ('Juliana', 'Elétrica'), ('Peterson', 'Elétrica'), ('Giliard', 'Elétrica'), ('Marilia', 'Elétrica'),
            ('Rafael', 'Mecânica'), ('Arnaldo', 'Mecânica'), ('Daniel', 'Mecânica'), ('Almoxarifado', 'Logistica')
        ]
        for p in equipe:
            cursor.execute("INSERT INTO projetistas (nome, especialidade) VALUES (%s, %s)", p)

    # 2. TABELA DE FASES DO KANBAN E MARCOS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kanban_fases (
            id SERIAL PRIMARY KEY,
            so TEXT,             -- NOVO: Para agrupar a Engenharia
            wo TEXT,             -- Para agrupar a Fábrica
            categoria TEXT, 
            fase TEXT, 
            responsavel TEXT, 
            data_inicio TIMESTAMP,
            data_prevista DATE,  -- NOVO: Meta de entrega da Engenharia
            data_fim TIMESTAMP,
            status TEXT 
        )
    ''')

    # Script de Migração Automática (Adiciona as colunas novas sem apagar seus dados)
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'kanban_fases'")
    col_k = [c[0] for c in cursor.fetchall()]
    if 'data_prevista' not in col_k:
        try: cursor.execute("ALTER TABLE kanban_fases ADD COLUMN data_prevista DATE")
        except: pass
    if 'so' not in col_k:
        try: cursor.execute("ALTER TABLE kanban_fases ADD COLUMN so TEXT")
        except: pass

    # 3. TABELA DE GESTÃO DE MATERIAIS FALTANTES (Com campos obrigatórios)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kanban_materiais (
            id SERIAL PRIMARY KEY,
            wo TEXT,
            codigo TEXT,
            descricao TEXT,
            quantidade INTEGER,
            data_apontamento TIMESTAMP,
            data_prevista_chegada DATE,
            data_recebimento DATE,
            status TEXT -- "Faltante", "Recebido"
        )
    ''')

    cursor.execute("SELECT COUNT(*) FROM parametros_jornada")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO parametros_jornada (data_inicio, data_fim, carga_seg_qui, carga_sexta, hora_saida_seg_qui, hora_saida_sexta) VALUES (%s, %s, %s, %s, %s, %s)", 
                       ('2020-01-01', None, 8.17, 6.25, '17:05', '15:00'))

    # Verificações de migração de colunas para PostgreSQL
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'apontamentos'")
    col_db = [c[0] for c in cursor.fetchall()]
    for col in ['customer', 'tipo_erro', 'causador_erro', 'so', 'product_name', 'foto_path', 'foto_depois_path', 'saldo_bh', 'linha']:
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
        
    # ⚡ Desativa a mágica para o resto do app funcionar com a segurança padrão
    conn.autocommit = False

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
    
    # Lógica de Sábado Alternado (Se trabalhou no último, este é o 2º consecutivo)
    is_sabado_consecutivo = False
    if is_sabado:
        sabado_anterior = (data_ref - timedelta(days=7)).strftime("%d/%m/%Y")
        c.execute("SELECT COUNT(*) FROM apontamentos WHERE matricula=%s AND data_registro=%s AND tipo IN ('Produção Normal', 'Retrabalho')", (matricula, sabado_anterior))
        trabalhou_antes = c.fetchone()
        if trabalhou_antes and trabalhou_antes[0] > 0:
            is_sabado_consecutivo = True
    
    carga_sq, carga_sex, hs_sq, hs_sex = obter_parametros_dia(conn_db, data_ref)
    
    # ⚡ NOVAS REGRAS DE LIMITES DE BANCO DE HORAS
    if data_ref.weekday() <= 3: 
        carga_diaria = carga_sq
        limite_bh_extra = 85 / 60.0 # 1h25m convertidos para decimal
    elif data_ref.weekday() == 4: 
        carga_diaria = carga_sex
        limite_bh_extra = 3.5 # 3h30m convertidos para decimal
    else: 
        carga_diaria = 0.0 
        limite_bh_extra = 0.0
        
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
                    e100 = round(net_h, 2) # Sábado Consecutivo = Hora Extra (100% ou 50% dependendo do seu acordo, aqui joga pro HE integral)
                else:
                    s_bh = round(net_h, 2) # Primeiro Sábado = Banco de Horas Total
            else:
                n = round(net_h, 2)
        else: 
            # Dias de Semana (Segunda a Sexta)
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
                # SEPARAÇÃO AUTOMÁTICA (Regra de Negócio)
                n_calc = min(net_h, carga_restante)
                extra_calc = net_h - n_calc
                carga_restante -= n_calc
                
                n = round(n_calc, 2)
                if extra_calc > 0:
                    # Envia para BH até bater o limite, o que sobrar vira HE50
                    bh_aplicado = min(extra_calc, limite_bh_extra)
                    he50_aplicado = extra_calc - bh_aplicado
                    s_bh = round(bh_aplicado, 2)
                    e50 = round(he50_aplicado, 2)
            
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
    if not caminho or caminho == 'N/A': return None 
    
    try:
        if str(caminho).startswith("http"):
            # Nova lógica: Baixa a foto direto do Supabase Storage
            response = requests.get(caminho)
            if response.status_code != 200: return None
            img = Image.open(BytesIO(response.content))
        else:
            # Lógica antiga (Retrocompatibilidade): Lê o arquivo antigo salvo localmente
            nome_arquivo = os.path.basename(str(caminho).replace('\\', '/'))
            caminho_real = os.path.join(PASTA_FOTOS, nome_arquivo)
            if not os.path.exists(caminho_real) or os.path.getsize(caminho_real) == 0: 
                return None 
            img = Image.open(caminho_real)

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
            
        img = img.resize((800, 600))
        
        # Salva a imagem processada temporariamente para o FPDF conseguir ler
        caminho_pdf = os.path.join(PASTA_FOTOS, f"temp_pdf_{int(time_sys.time() * 1000)}.jpg")
        img.save(caminho_pdf, "JPEG", quality=85)
        return caminho_pdf
    except Exception as e: 
        print(f"Erro ao processar imagem: {e}")
        return None

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
            SELECT a.data_registro as "Data", a.matricula as "Matricula", a.operador as "Operador", 
                   COALESCE(a.linha, c.linha) as "Linha Atuação", a.hora_inicio as "Inicio", a.hora_fim as "Fim", 
                   a.horas_normais as "Normais(h)", a.he_50 as "HE50(h)", a.he_100 as "HE100(h)", a.saldo_bh as "Banco(h)",
                   a.tipo as "Tipo", a.atividade as "Atividade", a.so as "SO", a.customer as "Cliente", a.wo as "WO", a.product_name as "Produto", 
                   a.unidade as "Unidade", a.descricao as "Observacoes"
            FROM apontamentos a
            LEFT JOIN colaboradores c ON a.matricula = c.matricula
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
            
            st.download_button(label="📥 Baixar Excel do Ponto", data=output.getvalue(), file_name=arq_nome, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
        else:
            st.info("Nenhum apontamento registrado neste período.")

# ==========================================
# 5. DETECÇÃO DE PAPEL (SECURITY RBAC)
# ==========================================
user_role = st.query_params.get("role", "admin").lower()

# ==========================================
# 6. NAVEGAÇÃO PRINCIPAL (MENU LATERAL)
# ==========================================
st.sidebar.markdown("---")

st.markdown("""
    <style>
    div[role="radiogroup"] { flex-direction: row; flex-wrap: wrap; gap: 10px; justify-content: center; }
    div[role="radiogroup"] > label { 
        background-color: #e9ecef; 
        padding: 8px 16px; 
        border-radius: 8px; 
        border: 1px solid #ced4da; 
        cursor: pointer;
    }
    div[role="radiogroup"] > label[data-checked="true"] { 
        background-color: #004a99; 
        border-color: #004a99;
    }
    div[role="radiogroup"] > label[data-checked="true"] p { color: white !important; }
    div[role="radiogroup"] > label > div:first-child { display: none; /* Esconde a bolinha */ }
    div[role="radiogroup"] > label p { font-weight: bold; margin: 0; }
    </style>
""", unsafe_allow_html=True)

menu_selecionado = st.radio(
    "Navegação", 
    [
        "📝 Lançamentos", 
        "🗂️ Kanban & Timeline", 
        "📋 Ordens de Produção",
        "📅 Planejamento de Carga",
        "📊 Dash. Projetos", 
        "👥 Dash. RH",
        "🔍 Manutenção",
        "📊 Auditoria BOM vs Real", # <--- ADICIONE ESTA LINHA AQUI NA LISTA 
        "📑 Relatórios PDF",
        "📈 Painel Executivo (BI)"
    ],
    horizontal=True,
    label_visibility="collapsed"
)
st.markdown("---")

# ------------------------------------------
# ABA: LANÇAMENTO & AUDITORIA
# ------------------------------------------
if menu_selecionado == "📝 Lançamentos":
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
                linhas_disponiveis = df_colab['linha'].dropna().unique().tolist()
                
                if colab_sel != "- Selecione -":
                    mat_selecionada = colab_sel.split(" - ")[0]
                    resultado_linha = df_colab[df_colab['matricula'] == mat_selecionada]['linha'].iloc[0]
                    if pd.notna(resultado_linha) and str(resultado_linha).strip() != "":
                        linha_colab = resultado_linha

                # NOVO: Campo visível para o líder alterar a linha real de trabalho
                linha_apontamento = st.selectbox(
                    "🏭 Linha de Atuação (Neste Apontamento)", 
                    options=["- Selecione -"] + linhas_disponiveis,
                    index=linhas_disponiveis.index(linha_colab) + 1 if linha_colab in linhas_disponiveis else 0,
                    help="O sistema sugere a linha de RH do operador, mas pode alterá-la caso ele esteja a cobrir outro setor."
                )

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
            
            if colab_sel != "- Selecione -" and tipo_ap == "Produção Normal":
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

            if st.button("💾 SALVAR APONTAMENTO", type="primary", width="stretch"):
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
                            nome_antes = f"{timestamp}_{so_id_db}_ANTES.jpg"
                            nome_depois = f"{timestamp}_{so_id_db}_DEPOIS.jpg"
                            
                            # 1. Faz o upload da foto em bytes direto para o seu Bucket
                            supabase_client.storage.from_("fotos_retrabalho").upload(
                                file=foto_antes.getvalue(), 
                                path=nome_antes, 
                                file_options={"content-type": "image/jpeg"}
                            )
                            supabase_client.storage.from_("fotos_retrabalho").upload(
                                file=foto_depois.getvalue(), 
                                path=nome_depois, 
                                file_options={"content-type": "image/jpeg"}
                            )
                            
                            # 2. Pega a URL pública permanente gerada pelo Supabase
                            path_f_antes = supabase_client.storage.from_("fotos_retrabalho").get_public_url(nome_antes)
                            path_f_depois = supabase_client.storage.from_("fotos_retrabalho").get_public_url(nome_depois)
                        
                        if fora_do_plano:
                            obs = f"{obs}\n[⚠️ DESVIO PCP]: {motivo_desvio}".strip()
                        
                        resolver_sobreposicoes(conn, mat_validar, data_br, hi, hf, data_lan)
                        
                        linha_salvar = linha_apontamento if linha_apontamento != "- Selecione -" else linha_colab
                        cursor.execute('''INSERT INTO apontamentos (data_registro, matricula, operador, linha, so, customer, wo, product_name, unidade, atividade, tipo, tipo_erro, causador_erro, hora_inicio, hora_fim, horas_normais, he_50, he_100, saldo_bh, descricao, foto_path, foto_depois_path) 
                                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,0,%s,%s,%s)''',
                                       (data_br, mat_validar, colab_sel.split(" - ")[1], linha_salvar, so_id_db, cliente_val, wo_id_db, prod_name_val, unidade_sel, atividade, tipo_ap, t_erro, c_erro, str(hi), str(hf), obs, path_f_antes, path_f_depois))
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
            
            if st.button("🚀 Processar Desconto de Banco de Horas em Lote", type="primary", width="stretch"):
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
                            
                            cursor.execute('''INSERT INTO apontamentos (data_registro, matricula, operador, linha, so, customer, wo, product_name, unidade, atividade, tipo, tipo_erro, causador_erro, hora_inicio, hora_fim, horas_normais, he_50, he_100, saldo_bh, descricao, foto_path, foto_depois_path) 
                                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,0,%s,%s,%s)''',
                                           (data_br_lote, row_op['matricula'], row_op['nome'], row_op['linha'], "N/A", "N/A", "N/A", "N/A", "Geral", "Banco de Horas", "Falta/Atraso", "N/A", "N/A", str(hi_lote), str(hf_lote), motivo_lote, "", ""))
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
                    st.dataframe(df_auditoria, width="stretch", height=145)
                else:
                    st.info("Nenhum lançamento efetuado nesta data.")
            else:
                st.info("👈 Selecione um operador à esquerda para visualizar sua auditoria.")

        # ==========================================
        # PAINEL DE GESTÃO DE APONTAMENTOS (Universal para Todos os Tipos)
        # ==========================================
        st.markdown("---")
        st.markdown("### 🛠️ Gerenciar / Corrigir Apontamentos")
        with st.expander("Clique aqui para corrigir horários, descrições ou classificações", expanded=False):
            st.caption("Dica: Selecione o apontamento abaixo para atualizar horários, categorias de parada, erros, causadores ou observações.")
            data_edit = st.date_input("1. Selecione a data do apontamento:", date.today(), format="DD/MM/YYYY", key="data_edit_apont")
            data_br_edit = data_edit.strftime("%d/%m/%Y")
            
            df_apont_edit = pd.read_sql_query("SELECT id, matricula, operador, hora_inicio, hora_fim, tipo, atividade, wo, descricao, tipo_erro, causador_erro FROM apontamentos WHERE data_registro = %(dt)s", engine, params={"dt": data_br_edit})
            
            if not df_apont_edit.empty:
                lista_apont = ["- Selecione -"] + [f"ID {r['id']} | {r['operador']} | {r['hora_inicio']} às {r['hora_fim']} | {r['tipo']}" for _, r in df_apont_edit.iterrows()]
                apont_sel = st.selectbox("2. Selecione o apontamento que deseja corrigir:", lista_apont, key="apont_sel_edit")
                
                if apont_sel != "- Selecione -":
                    id_apont = str(apont_sel.split(" | ")[0].replace("ID ", "")).strip()
                    filtro_ap = df_apont_edit[df_apont_edit['id'].astype(str) == id_apont]
                    
                    if not filtro_ap.empty:
                        row_apont = filtro_ap.iloc[0]
                        st.info(f"**Detalhes Atuais:**\n\n**WO:** {row_apont['wo']} | **Tipo:** {row_apont['tipo']}")
                        
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
                        
                        # Variáveis auxiliares para alteração
                        novo_tipo_erro = row_apont['tipo_erro']
                        novo_causador = row_apont['causador_erro']
                        nova_atividade = row_apont['atividade']
                        
                        # --- TRATAMENTO INTELIGENTE CONFORME O TIPO DE APONTAMENTO ---
                        if row_apont['tipo'] == 'Retrabalho':
                            df_erros_ed = pd.read_sql_query("SELECT erro FROM tipos_erro", engine)
                            df_causadores_ed = pd.read_sql_query("SELECT causador FROM causadores_erro", engine)
                            
                            lista_erros_db = df_erros_ed['erro'].tolist() if not df_erros_ed.empty else ["Nenhum cadastrado"]
                            lista_caus_db = df_causadores_ed['causador'].tolist() if not df_causadores_ed.empty else ["Nenhum cadastrado"]
                            
                            idx_err = lista_erros_db.index(row_apont['tipo_erro']) if row_apont['tipo_erro'] in lista_erros_db else 0
                            idx_cau = lista_caus_db.index(row_apont['causador_erro']) if row_apont['causador_erro'] in lista_caus_db else 0
                            
                            ce_err, ce_cau = st.columns(2)
                            novo_tipo_erro = ce_err.selectbox("Editar Tipo de Erro", lista_erros_db, index=idx_err, key="edit_tipo_erro")
                            novo_causador = ce_cau.selectbox("Editar Causador", lista_caus_db, index=idx_cau, key="edit_causador")
                            
                        elif row_apont['tipo'] == 'Parada':
                            df_paradas_ed = pd.read_sql_query("SELECT categoria FROM categorias_parada", engine)
                            lista_paradas_db = df_paradas_ed['categoria'].tolist() if not df_paradas_ed.empty else ["Nenhuma cadastrada"]
                            
                            idx_par = lista_paradas_db.index(row_apont['atividade']) if row_apont['atividade'] in lista_paradas_db else 0
                            nova_atividade = st.selectbox("Editar Categoria da Parada", lista_paradas_db, index=idx_par, key="edit_cat_parada")
                        # -------------------------------------------------------------

                        desc_atual = row_apont['descricao'] if pd.notna(row_apont['descricao']) else ""
                        nova_obs = st.text_area("Editar Observação / Descrição", value=desc_atual, key="obs_edit_apont")
                        
                        st.write("")
                        c_btn_e1, c_btn_e2 = st.columns([1, 1])
                        
                        if c_btn_e1.button("💾 Salvar Alterações", type="primary", use_container_width=True):
                            # Atualiza a Query gravando todas as variações possíveis (Erros, Causadores, Paradas e Observações)
                            cursor.execute(
                                "UPDATE apontamentos SET hora_inicio=%s, hora_fim=%s, descricao=%s, tipo_erro=%s, causador_erro=%s, atividade=%s WHERE id=%s", 
                                (str(hi_edit), str(hf_edit), nova_obs, novo_tipo_erro, novo_causador, nova_atividade, id_apont)
                            )
                            conn.commit()
                            recalcular_dia(conn, row_apont['matricula'], data_br_edit)
                            st.success("✔️ Apontamento atualizado com sucesso!")
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
elif menu_selecionado == "📊 Dash. Projetos":
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
            st.plotly_chart(fig_gauge, width="stretch", config={'displayModeBar': False}, key="gauge_main_proj")
            
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
        SELECT COALESCE(a.linha, c.linha) as linha, 
               SUM(CASE WHEN a.tipo = 'Produção Normal' THEN a.horas_normais + a.he_50 + a.he_100 ELSE 0 END) as consumo_prod,
               SUM(CASE WHEN a.tipo IN ('Retrabalho', 'Parada') THEN a.horas_normais + a.he_50 + a.he_100 ELSE 0 END) as consumo_perdas
        FROM apontamentos a 
        LEFT JOIN colaboradores c ON a.matricula = c.matricula
        WHERE a.so = %(so)s AND a.tipo IN ('Produção Normal', 'Retrabalho', 'Parada') 
        AND COALESCE(a.linha, c.linha) IS NOT NULL AND TRIM(COALESCE(a.linha, c.linha)) != '' AND COALESCE(a.linha, c.linha) != 'None'
        GROUP BY COALESCE(a.linha, c.linha)
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
                
                st.plotly_chart(fig_l, width="stretch", config={'displayModeBar': False}, key=f"gauge_linha_{idx}")
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
            st.plotly_chart(fig_pie_he, width="stretch", key="pie_he_proj_micro")
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
            st.plotly_chart(fig_bar_he, width="stretch", key="bar_he_proj_macro")
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
            st.dataframe(df_kardex, width="stretch")

            output_kardex = io.BytesIO()
            with pd.ExcelWriter(output_kardex, engine='openpyxl') as writer:
                df_kardex.to_excel(writer, index=False, sheet_name='Kardex_Projeto')

            st.download_button(
                label=f"📥 Baixar Kardex em Excel (.xlsx)",
                data=output_kardex.getvalue(),
                file_name=f"Kardex_Projeto_{so_dash_clean}_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch"
            )
        else:
            st.info("Nenhum apontamento encontrado para este projeto.")


# ------------------------------------------
# ABA: DASHBOARD RH (RECURSOS HUMANOS)
# ------------------------------------------
elif menu_selecionado == "👥 Dash. RH":
    if user_role == "viewer":
        st.error("🔒 Acesso Restrito - Modo de Visualização Gerencial (Apenas Leitura)")
    else:
        st.markdown("## 👥 Painel de Recursos Humanos")
        
        st.markdown("### 🕒 Acompanhamento Diário de Ponto (Saldo de Horas)")
        
        df_lucy_check_rh = pd.read_sql_query("SELECT lucy_month, MIN(start_date) as start_date, MAX(end_date) as end_date FROM calendario_lucy GROUP BY lucy_month ORDER BY MIN(start_date) DESC", engine)
        
        if not df_lucy_check_rh.empty and df_lucy_check_rh['lucy_month'].iloc[0] is not None:
            meses_lucy = [f"{r['lucy_month']} (De {pd.to_datetime(r['start_date']).strftime('%d/%m/%Y')} a {pd.to_datetime(r['end_date']).strftime('%d/%m/%Y')})" for _, r in df_lucy_check_rh.iterrows()]
            
            # --- NOVO: Lógica para encontrar o índice do mês atual ---
            hoje_data = date.today()
            idx_atual = 0
            for i, r in df_lucy_check_rh.iterrows():
                d_ini = pd.to_datetime(r['start_date']).date()
                d_fim = pd.to_datetime(r['end_date']).date()
                if d_ini <= hoje_data <= d_fim:
                    idx_atual = i
                    break
            # ---------------------------------------------------------
            
            mes_escolhido_rh = st.selectbox("Selecione o Mês Fiscal Lucy:", meses_lucy, index=idx_atual)
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
        
        # --- CORREÇÃO DO BANCO DE HORAS (COMPATÍVEL COM HISTÓRICO ANTIGO) ---
        def get_horas_efetivas_dia(r):
            # 1. Banco de Horas (justifica a ausência para o saldo diário zerar e ficar verde)
            if 'Banco de Horas' in str(r['atividade']):
                h_norm = float(r['horas_normais'] or 0)
                if h_norm > 0:
                    return h_norm
                else:
                    return abs(float(r['saldo_bh'] or 0))
                    
            # 2. Atestado Médico E Declaração Médica (justificam a ausência, ficam verde)
            elif r['tipo'] == 'Atestado / Justificada' or 'Declaração Médica' in str(r['atividade']):
                return float(r['horas_normais'] or 0)
                
            # 3. Falta Injustificada Real (não abate a meta diária, fica vermelho)
            elif r['tipo'] == 'Falta/Atraso':
                return 0.0
                
            # 4. Dias Normais de Trabalho
            else:
                h_norm = float(r['horas_normais'] or 0)
                he_50 = float(r['he_50'] or 0)
                he_100 = float(r['he_100'] or 0)
                bh_credito = max(0, float(r['saldo_bh'] or 0)) # Apenas soma se for BH positivo (crédito)
                return h_norm + he_50 + he_100 + bh_credito

        df_ap_rh['total_horas'] = df_ap_rh.apply(get_horas_efetivas_dia, axis=1)
        # --------------------------------------------------------------------
        
        apont_dict = {}
        for _, r in df_ap_rh.groupby(['operador', 'data_registro'])['total_horas'].sum().reset_index().iterrows():
            apont_dict[(r['operador'], r['data_registro'])] = r['total_horas']
        
        # --- OTIMIZAÇÃO DE PERFORMANCE (PASSO 2) ---
        df_params = pd.read_sql_query("SELECT data_inicio, data_fim, carga_seg_qui, carga_sexta FROM parametros_jornada ORDER BY data_inicio DESC", engine)

        def get_carga_rapida(data_ref):
            d_str = data_ref.strftime('%Y-%m-%d')
            for _, r in df_params.iterrows():
                d_ini = r['data_inicio']
                d_fim = r['data_fim']
                if d_ini <= d_str and (pd.isna(d_fim) or d_fim is None or str(d_fim) == '' or str(d_fim) >= d_str):
                    return float(r['carga_seg_qui']), float(r['carga_sexta'])
            return 8.17, 6.25 

        ferias_set = set()
        for _, vf in df_ferias_rh.iterrows():
            mat_f = vf['matricula']
            try:
                start_f = pd.to_datetime(vf['data_inicio']).date()
                end_f = pd.to_datetime(vf['data_fim']).date()
                for i in range((end_f - start_f).days + 1):
                    ferias_set.add((mat_f, start_f + timedelta(days=i)))
            except: pass

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
                
                em_ferias = (mat, d) in ferias_set
                is_feriado = d_str_iso in feriados_bd or d.weekday() == 6
                
                if em_ferias or is_feriado:
                    meta = 0.0
                else:
                    c_sq, c_sx = get_carga_rapida(d) 
                    if d.weekday() <= 3: meta = c_sq
                    elif d.weekday() == 4: meta = c_sx
                    else: meta = 0.0
                    
                cap_mensal_operador += meta
                
                apontado = apont_dict.get((colab['nome'], d_str_br_full), 0.0)
                saldo = apontado - meta
                linha_ponto[d_str_br_curto] = round(saldo, 2)
                
            tabela_ponto.append(linha_ponto)
            # Adicionado a linha para permitir o cálculo correto por setor no absenteísmo
            dados_carga_rh.append({'operador': colab['nome'], 'linha': colab['linha'], 'capacidade': cap_mensal_operador})
            
        df_ponto_final = pd.DataFrame(tabela_ponto)
        
        if not df_ponto_final.empty:
            df_ponto_final.set_index('Operador', inplace=True)
            try:
                styled_df = df_ponto_final.style.map(color_ponto, subset=[d.strftime("%d/%m") for d in dias_mes if d.strftime("%d/%m") in df_ponto_final.columns])
            except AttributeError:
                styled_df = df_ponto_final.style.applymap(color_ponto, subset=[d.strftime("%d/%m") for d in dias_mes if d.strftime("%d/%m") in df_ponto_final.columns])
            st.dataframe(styled_df, width="stretch")

        st.markdown("---")

        st.markdown("### 📊 Análise de Capacidade vs Apontamento")
        st.write("A barra verde ao fundo representa a disponibilidade do colaborador. As colunas coloridas representam o que foi apontado.")
        
        df_carga = pd.DataFrame(dados_carga_rh)
        
        # Alterado: Só exige que a tabela de carga (colaboradores) exista
        if not df_carga.empty:
            if not df_ap_rh.empty:
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
            else:
                # NOVO: Se não houver apontamentos, cria estrutura zerada para mesclar
                df_consumo_op = pd.DataFrame(columns=['operador', 'h_normais', 'paradas', 'atestados', 'banco_horas', 'he50', 'he100'])
            
            df_consumo_op['total_apontado'] = df_consumo_op[['h_normais', 'paradas', 'atestados', 'banco_horas', 'he50', 'he100']].sum(axis=1) if not df_consumo_op.empty else 0
            
            df_plot_carga = pd.merge(df_carga, df_consumo_op, on='operador', how='left').fillna(0)
            df_plot_carga = df_plot_carga.sort_values(by='total_apontado', ascending=False)
            
            # --- CAPACIDADE LÍQUIDA ---
            df_plot_carga['capacidade_liquida'] = df_plot_carga['capacidade'] - df_plot_carga['banco_horas']
            df_plot_carga['capacidade_liquida'] = df_plot_carga['capacidade_liquida'].apply(lambda x: max(0, x))
            
            # --- BASES DA COLUNA 2 (APONTAMENTOS) ---
            # Removemos o Banco de Horas daqui!
            base_paradas = df_plot_carga['h_normais']
            base_atestados = base_paradas + df_plot_carga['paradas']
            base_he50 = base_atestados + df_plot_carga['atestados'] # Pula o BH e vai direto pro HE
            base_he100 = base_he50 + df_plot_carga['he50']
            
            # --- BASES DA COLUNA 1 (CAPACIDADE) ---
            base_bh_capacidade = df_plot_carga['capacidade_liquida']
            
            # TOTALIZADORES
            tot_cap = df_plot_carga['capacidade_liquida'].sum()
            tot_hn = df_plot_carga['h_normais'].sum()
            tot_par = df_plot_carga['paradas'].sum()
            tot_ate = df_plot_carga['atestados'].sum()
            tot_bh = df_plot_carga['banco_horas'].sum()
            tot_he50 = df_plot_carga['he50'].sum()
            tot_he100 = df_plot_carga['he100'].sum()
            
            fig_carga = go.Figure()
            
            # ==========================================
            # COLUNA 1: A RÉGUA DE CAPACIDADE (offsetgroup=0)
            # ==========================================
            # Base verde escuro: O tempo que a empresa de facto tem para usar
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['capacidade_liquida'], name=f'Disp. Líquida ({tot_cap:.1f}h)', marker_color='#28a745', offsetgroup=0))
            
            # Topo verde claro: O tempo que a empresa abriu mão (Banco de Horas) empilhado em cima
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['banco_horas'], name=f'Folga / BH ({tot_bh:.1f}h)', marker_color='#85e0a3', offsetgroup=0, base=base_bh_capacidade))
            
            # ==========================================
            # COLUNA 2: O QUE FOI APONTADO (offsetgroup=1)
            # ==========================================
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['h_normais'], name=f'Normais/Trab. ({tot_hn:.1f}h)', marker_color='#004a99', offsetgroup=1, base=0))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['paradas'], name=f'Paradas ({tot_par:.1f}h)', marker_color='#ffc107', offsetgroup=1, base=base_paradas))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['atestados'], name=f'Atestados/Faltas ({tot_ate:.1f}h)', marker_color='#dc3545', offsetgroup=1, base=base_atestados))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['he50'], name=f'HE 50% ({tot_he50:.1f}h)', marker_color='#fd7e14', offsetgroup=1, base=base_he50))
            fig_carga.add_trace(go.Bar(x=df_plot_carga['operador'], y=df_plot_carga['he100'], name=f'HE 100% ({tot_he100:.1f}h)', marker_color='#d9480f', offsetgroup=1, base=base_he100))
            
            fig_carga.update_layout(barmode='group', height=450, margin=dict(l=20, r=20, t=30, b=20),
                                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
            st.plotly_chart(fig_carga, width="stretch", key="bar_carga_rh")
        else:
            st.info("Sem dados para a visão de capacidade.")

        st.markdown("---")
        
        col_rh_bot1, col_rh_bot2 = st.columns(2)
        
        with col_rh_bot1:
            st.markdown("### 🤒 Absenteísmo da Fábrica")
            
            if not df_ap_rh.empty and 'dados_carga_rh' in locals() and dados_carga_rh:
                df_abs = pd.merge(df_ap_rh, df_colab_rh[['nome', 'linha']], left_on='operador', right_on='nome', how='left')
                df_carga_abs = pd.DataFrame(dados_carga_rh)
                
                linhas_disp = ["- Todas as Linhas -"] + df_abs['linha'].dropna().unique().tolist()
                linha_sel = st.selectbox("Filtro por Setor/Linha:", linhas_disp, key="sb_linha_rh_abs")
                
                if linha_sel != "- Todas as Linhas -":
                    df_abs = df_abs[df_abs['linha'] == linha_sel]
                    df_carga_abs = df_carga_abs[df_carga_abs['linha'] == linha_sel]
                
                # 1. NUMERADOR: Atestados + Declarações + Faltas + Atrasos (Exclui Banco de Horas)
                df_abs['is_ausencia'] = df_abs.apply(lambda r: r['tipo'] in ['Falta/Atraso', 'Atestado / Justificada'] and 'Banco de Horas' not in str(r['atividade']), axis=1)
                total_ausencia = df_abs[df_abs['is_ausencia']]['horas_normais'].sum()
                
                # 2. BANCO DE HORAS: Horas que o colaborador foi dispensado para ficar em casa
                df_abs['is_folga_bh'] = df_abs.apply(lambda r: 'Banco de Horas' in str(r['atividade']), axis=1)
                total_folga_bh = df_abs[df_abs['is_folga_bh']]['horas_normais'].sum()
                
                # 3. HORAS DISPONÍVEIS: Capacidade nominal de contrato vinda dos parâmetros de jornada do mês
                horas_disponiveis = df_carga_abs['capacidade'].sum()
                
                # 4. DENOMINADOR: Horas Disponíveis - Banco de Horas
                denominador = horas_disponiveis - total_folga_bh
                
                taxa_geral = (total_ausencia / denominador * 100) if denominador > 0 else 0.0
                
                if denominador > 0:
                    fig_pie = px.pie(names=['Disponibilidade Líquida', 'Ausências (Absenteísmo Real)'], 
                                    values=[max(0, denominador - total_ausencia), total_ausencia],
                                    title=f"Taxa de Absenteísmo Real: {taxa_geral:.1f}%",
                                    color_discrete_sequence=['#28a745', '#dc3545'])
                    fig_pie.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
                    st.plotly_chart(fig_pie, width="stretch", key="pie_abs_rh")
                else:
                    st.info("Sem horas disponíveis líquidas para calcular o absenteísmo neste filtro.")
            else:
                st.info("Sem dados de capacidade ou apontamentos suficientes para gerar o gráfico.")

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
                    st.plotly_chart(fig_ind, width="stretch", key="pie_ind_rh")
                else:
                    st.info("Colaborador não tem apontamentos suficientes neste mês.")
            else:
                st.info("Sem dados para análise individual.")

# ------------------------------------------
# ABA: ORDENS DE PRODUÇÃO
# ------------------------------------------
elif menu_selecionado == "📋 Ordens de Produção":
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
                    wo_n = st.text_input("Work Order (WO) - Deixe em branco para Reserva de Slot")
                    item_n = st.text_input("Item (Opcional)") 
                    linha_n = st.selectbox("Linha de Produção Predominante*", ["- Selecione -"] + linhas_disponiveis)
                    cli_n = st.text_input("Cliente*")
                    prod_n = st.text_input("Nome do Produto / Descrição da Reserva*")
                    
                    qtd_n = st.number_input("Quantidade*", min_value=1, step=1)
                    hr_ven = st.number_input("Horas Vendidas / Estimadas*", min_value=0.0, step=0.5, value=0.0)
                    
                    if st.form_submit_button("💾 Criar Ordem / Reserva", type="primary", width="content"):
                        if not so_n or not cli_n or not prod_n or linha_n == "- Selecione -" or hr_ven <= 0:
                            st.error("❌ Preencha os campos obrigatórios (*). As Horas Vendidas/Estimadas devem ser maiores que zero.")
                        else:
                            # MÁGICA AQUI: Gera WO temporária se ficar em branco e define status especial
                            is_reserva = not wo_n.strip()
                            wo_final = f"RES-{int(time_sys.time() % 100000)}" if is_reserva else wo_n.strip()
                            item_final = "-" if not item_n.strip() else item_n.strip()
                            status_inicial = "Reserva Estratégica" if is_reserva else "Não iniciada"
                            
                            cursor.execute("""
                                INSERT INTO projetos (so, wo, linha, customer, item, product_name, qtde, status_producao, horas_vendidas) 
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """, (so_n.strip(), wo_final, linha_n, cli_n.strip(), item_final, prod_n.strip(), qtd_n, status_inicial, hr_ven))
                            conn.commit()
                            st.success(f"✔️ {'Reserva de Slot' if is_reserva else 'Ordem de Produção'} registrada com sucesso!")
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
                                
                                if c_btn1.button("💾 Atualizar Dados", type="primary", width="content"):
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
                                        
                                if c_btn2.button("🗑️ Excluir Ordem", width="content"):
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
        st.dataframe(pd.read_sql_query("SELECT so, wo, item, linha, customer, product_name, qtde, horas_vendidas, status_producao FROM projetos", engine), width="stretch", height=400)


# ------------------------------------------
# ABA: PLANEJAMENTO E ALOCAÇÃO 
# ------------------------------------------
elif menu_selecionado == "📅 Planejamento de Carga":
    st.markdown("## 📅 Planejamento de Carga de Máquina e Operador")
    
    if user_role != "viewer":
        col_plan1, col_plan2 = st.columns(2)
        with col_plan1:
            with st.container(border=True):
                st.markdown("### ➕ Planejamento Preditivo (MRP)")
                
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
                                
                                # --- CHAVES (KEYS) ADICIONADAS PARA IMPEDIR A QUEBRA DAS ABAS ---
                                unidade_plan_sel = st.selectbox("3. Unidade a Planejar", lista_unidades_plan, key="und_plan_sel_mrp")

                                horas_bd = float(wo_data['horas_vendidas']) if pd.notna(wo_data['horas_vendidas']) and wo_data['horas_vendidas'] > 0 else 8.0
                                horas_base = st.number_input("4. Horas Estimadas (Base)", min_value=0.5, step=0.5, value=horas_bd, key="hr_base_sel_mrp")
                                fator_seguranca = st.slider("5. Fator de Segurança (%)", min_value=0, max_value=50, value=10, step=5, key="fat_seg_sel_mrp")

                                horas_totais_com_fator = round(horas_base * (1 + (fator_seguranca / 100.0)), 2)
                                st.markdown(f"Horas Totais a Alocar (com margem): <span style='color:#004a99; font-weight:bold; font-size:18px;'>{horas_totais_com_fator}h</span>", unsafe_allow_html=True)

                                linha_wo = wo_data['linha']
                                if pd.notna(linha_wo) and str(linha_wo).lower() != "nan" and str(linha_wo) != "None" and str(linha_wo).strip() != "":
                                    df_colab_plan = pd.read_sql_query("SELECT matricula, nome FROM colaboradores WHERE (data_demissao IS NULL OR data_demissao = '') AND linha = %(linha)s", engine, params={"linha": str(linha_wo)})
                                else:
                                    df_colab_plan = pd.read_sql_query("SELECT matricula, nome FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''", engine)

                                if df_colab_plan.empty:
                                    st.warning(f"Nenhum colaborador encontrado para a linha '{linha_wo}'.")
                                    lista_ops = []
                                else:
                                    lista_ops = [f"{r['matricula']} - {r['nome']}" for _, r in df_colab_plan.iterrows()]

                                ops_selecionados = st.multiselect("5. Operador(es)", lista_ops, key="ops_sel_mrp_mult")

                                data_referencia = st.date_input("6. Data de Referência (Início ou Entrega)", date.today() + timedelta(days=7), format="DD/MM/YYYY", key="dt_ref_mrp_input")

                                alerta_duplicidade = False
                                ja_planejado = pd.read_sql_query("SELECT DISTINCT c.nome FROM planejamento p JOIN colaboradores c ON p.matricula = c.matricula WHERE p.wo = %(wo)s AND p.unidade = %(und)s", engine, params={"wo": wo_clean, "und": unidade_plan_sel})
                                if not ja_planejado.empty:
                                    nomes_ja = ", ".join(ja_planejado['nome'].tolist())
                                    st.warning(f"⚠️ Atenção: A {unidade_plan_sel} desta WO já possui planejamento para: {nomes_ja}. Utilize o Replanejamento ao lado para limpar antes de prosseguir se desejar refazer.")
                                    alerta_duplicidade = True
                                    
                                col_b1, col_b2 = st.columns(2)
                                btn_reverso = col_b1.button("⏪ Planejar P/ Trás (Reverso)", type="primary", width="stretch", help="A data escolhida acima será o prazo final.")
                                btn_direto = col_b2.button("⏩ Planejar P/ Frente (Direto)", type="primary", width="stretch", help="A data escolhida acima será o dia de início.")

                                if btn_reverso or btn_direto:
                                    if not ops_selecionados:
                                        st.error("❌ Selecione pelo menos um operador.")
                                    elif alerta_duplicidade:
                                        st.error("❌ Limpe o planejamento antigo desta WO/Unidade antes de refazer a alocação.")
                                    else:
                                        passo_dias = -1 if btn_reverso else 1
                                        nome_estrategia = "Reverso" if btn_reverso else "Direto"
                                        
                                        so_plan = so_sel_plan
                                        horas_por_op = horas_totais_com_fator / len(ops_selecionados)
                                        
                                        alocacoes_temp = []
                                        datas_protegidas_alerta = []
                                        
                                        for op in ops_selecionados:
                                            mat_plan = op.split(" - ")[0]
                                            nome_op = op.split(" - ")[1]
                                            horas_restantes = horas_por_op
                                            data_atual_loop = data_referencia
                                            
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
                                                    data_atual_loop += timedelta(days=passo_dias) 
                                                    continue
                                                
                                                cursor.execute("SELECT SUM(horas_normais) FROM apontamentos WHERE matricula = %s AND data_registro = %s AND tipo IN ('Atestado / Justificada', 'Falta/Atraso')", (mat_plan, data_br_loop))
                                                res = cursor.fetchone()
                                                ausencia_agendada = float(res[0]) if res and res[0] else 0.0
                                                
                                                cursor.execute("SELECT COUNT(*) FROM planejamento WHERE matricula = %s AND data_planejada = %s AND wo != %s", (mat_plan, data_iso_loop, wo_clean))
                                                ja_ocupado_dia = cursor.fetchone()[0]
                                                
                                                if ja_ocupado_dia > 0:
                                                    datas_protegidas_alerta.append(f"{nome_op} ({data_br_loop})")
                                                    data_atual_loop += timedelta(days=passo_dias)
                                                    continue
                                                    
                                                c_sq, c_sx, _, _ = obter_parametros_dia(conn, data_atual_loop)
                                                cap_dia = c_sq if data_atual_loop.weekday() <= 3 else c_sx
                                                
                                                cap_dia -= ausencia_agendada
                                                
                                                if cap_dia <= 0.05:
                                                    data_atual_loop += timedelta(days=passo_dias) 
                                                    continue
                                                
                                                cursor.execute("SELECT SUM(horas_planejadas) FROM planejamento WHERE matricula = %s AND data_planejada = %s AND wo = %s", (mat_plan, data_iso_loop, wo_clean))
                                                res_ja_plan = cursor.fetchone()
                                                ja_plan_mesmo_projeto = float(res_ja_plan[0]) if res_ja_plan and res_ja_plan[0] else 0.0
                                                
                                                cap_disponivel = cap_dia - ja_plan_mesmo_projeto
                                                
                                                if cap_disponivel <= 0:
                                                    data_atual_loop += timedelta(days=passo_dias) 
                                                    continue
                                                    
                                                alocar_agora = min(cap_disponivel, horas_restantes)
                                                alocar_agora = round(alocar_agora, 2)
                                                
                                                alocacoes_temp.append((data_iso_loop, mat_plan, so_plan, wo_clean, unidade_plan_sel, alocar_agora))
                                                horas_restantes -= alocar_agora
                                                
                                                if horas_restantes > 0.01:
                                                    data_atual_loop += timedelta(days=passo_dias) 
                                                    
                                        for aloc in alocacoes_temp:
                                            cursor.execute("INSERT INTO planejamento (data_planejada, matricula, so, wo, unidade, horas_planejadas) VALUES (%s,%s,%s,%s,%s,%s)", aloc)
                                        conn.commit()
                                        
                                        st.success(f"✔️ Planejamento {nome_estrategia} gravado com sucesso!")
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
                            if st.button("🗑️ Excluir Cronograma do Período", width="content"):
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
        
        # --- NOVO: Lógica para encontrar o mês atual ---
        hoje_data = date.today()
        idx_mes_atual = 1 # O índice 0 será o "Ver Tudo", então começamos no 1
        for i, r in df_lucy_gantt_check.iterrows():
            d_ini = pd.to_datetime(r['start_date']).date()
            d_fim = pd.to_datetime(r['end_date']).date()
            if d_ini <= hoje_data <= d_fim:
                idx_mes_atual = i + 1 
                break
        # ----------------------------------------------
        
        col_fil_g1, col_fil_g2 = st.columns(2)
        with col_fil_g1:
            mes_gantt_sel = st.selectbox("Filtrar Período do Cronograma:", ["Ver Tudo"] + meses_gantt_list, index=idx_mes_atual, key="sb_gantt_mes")
        
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
            
            # ADICIONADA A KEY AQUI PARA PARAR O CONGELAMENTO
            so_iso_sel = st.selectbox("🔍 Isolar Caminho de um Projeto (SO):", lista_isolamento, key="so_iso_sel_gantt_filtro")
            
            if so_iso_sel != "- Mostrar Todos os Projetos (Fábrica) -":
                so_clean_iso = so_iso_sel.split(" - ")[0].strip()
                
                # 1. Identifica quais operadores estão alocados neste projeto específico
                ops_do_projeto = df_gantt_raw[df_gantt_raw['so'] == so_clean_iso]['operador'].unique()
                
                # 2. Filtra o Gantt para mostrar apenas o projeto E as ausências exclusivas dessa equipe
                df_gantt_raw = df_gantt_raw[
                    (df_gantt_raw['so'] == so_clean_iso) | 
                    ((df_gantt_raw['so'] == '⏸️ AFASTAMENTO') & (df_gantt_raw['operador'].isin(ops_do_projeto)))
                ]
        else:
            st.selectbox("🔍 Isolar Caminho de um Projeto (SO):", ["- Sem Planejamentos Ativos -"], disabled=True, key="so_iso_sel_gantt_filtro_vazio")
            
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
        
        # 🎨 SUPER PALETA: Combina várias paletas para gerar 74 cores únicas antes de repetir
        super_paleta = px.colors.qualitative.Alphabet + px.colors.qualitative.Light24 + px.colors.qualitative.Dark24
        
        color_discrete_map = {so: super_paleta[i % len(super_paleta)] for i, so in enumerate(todas_sos)}
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
            
            st.dataframe(df_export, width="stretch")
            
            output_plan = io.BytesIO()
            with pd.ExcelWriter(output_plan, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Cronograma_PCP')
                
            st.download_button(
                label="📥 Baixar Tabela em Excel (.xlsx)", 
                data=output_plan.getvalue(), 
                file_name=f"Cronograma_PCP_{date.today().strftime('%Y%m%d')}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch"
            )
            
    else:
        # --- NOVO: Desenha um gráfico vazio se não houver planejamento ---
        fig_gantt_vazio = go.Figure()
        fig_gantt_vazio.update_layout(
            title="Gantt Avançado Lucy Group (Sem planejamento no período)",
            xaxis_title="Período Cronograma (Dias)",
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            height=200,
            margin=dict(l=10, r=20, t=40, b=20),
            plot_bgcolor="#f5f7f9"
        )
        st.plotly_chart(fig_gantt_vazio, use_container_width=True, key="chart_gantt_vazio")
        st.info("Nenhuma alocação ou apontamento de horas encontrado para o mês/filtro selecionado.")
        
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

            # --- NOVA LÓGICA: BUSCAR DISPENSAS (BANCO DE HORAS) DO PERÍODO ---
            # Atualizado para ler tanto os apontamentos novos quanto o histórico antigo
            df_ap_bh = pd.read_sql_query("SELECT matricula, data_registro, atividade, horas_normais, saldo_bh FROM apontamentos WHERE atividade LIKE '%%Banco de Horas%%'", engine)
            
            df_ap_bh['data_dt'] = pd.to_datetime(df_ap_bh['data_registro'], format='%d/%m/%Y', errors='coerce').dt.date
            df_ap_bh = df_ap_bh[(df_ap_bh['data_dt'] >= dt_start_cap) & (df_ap_bh['data_dt'] <= dt_end_cap)]
            df_ap_bh = pd.merge(df_ap_bh, df_colabs_ativos_bal[['matricula', 'linha']], on='matricula', how='inner')
            
            # Regra inteligente: se não tem horas normais, puxa o débito do saldo (compatibilidade)
            df_ap_bh['bh_desconto'] = df_ap_bh.apply(lambda r: float(r['horas_normais']) if float(r['horas_normais'] or 0) > 0 else abs(float(r['saldo_bh'] or 0)), axis=1)
            
            bh_desconto_linha = df_ap_bh.groupby('linha')['bh_desconto'].sum().to_dict()
            # -----------------------------------------------------------------
            
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

            # --- APLICAR O DESCONTO DE BANCO DE HORAS NA CAPACIDADE ---
            for linha in cap_linha:
                desconto = bh_desconto_linha.get(linha, 0.0)
                cap_linha[linha] = max(0, cap_linha[linha] - desconto) # Impede que fique negativo
            
            cap_total_fabrica = max(0, cap_total_fabrica - sum(bh_desconto_linha.values()))
            # ----------------------------------------------------------

            if not df_gantt_raw.empty:
                df_plan_clean = df_gantt_raw[df_gantt_raw['so'] != '⏸️ AFASTAMENTO']
                df_plan_agrupado = df_plan_clean.groupby('linha')['horas_planejadas'].sum().reset_index()
                total_plan_fabrica = df_plan_clean['horas_planejadas'].sum()
            else:
                df_plan_agrupado = pd.DataFrame(columns=['linha', 'horas_planejadas'])
                total_plan_fabrica = 0.0
                
            # --- PREPARANDO OS DADOS PARA O GRÁFICO ---
            df_capacidade = pd.DataFrame(list(cap_linha.items()), columns=['linha', 'capacidade_h'])
            df_bh_desconto = pd.DataFrame(list(bh_desconto_linha.items()), columns=['linha', 'banco_horas'])
            
            # Junta a Capacidade, o Planejado e o Banco de Horas na mesma tabela
            df_balanco = pd.merge(df_capacidade, df_plan_agrupado, on='linha', how='left').fillna(0)
            df_balanco = pd.merge(df_balanco, df_bh_desconto, on='linha', how='left').fillna(0)
            
            df_balanco['ocupacao_pct'] = ((df_balanco['horas_planejadas'] / df_balanco['capacidade_h']) * 100).fillna(0)
            df_balanco['saldo_h'] = df_balanco['capacidade_h'] - df_balanco['horas_planejadas']
            
            ocup_global_pct = (total_plan_fabrica / cap_total_fabrica * 100) if cap_total_fabrica > 0 else 0
            saldo_global = cap_total_fabrica - total_plan_fabrica
            
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Capacidade Total Líquida", f"{cap_total_fabrica:.0f}h")
            col_m2.metric("Horas Planejadas", f"{total_plan_fabrica:.0f}h")
            col_m3.metric("Saldo Livre (Ociosidade)", f"{saldo_global:.0f}h", delta=f"{saldo_global:.0f}h", delta_color="normal" if saldo_global >= 0 else "inverse")
            col_m4.metric("Ocupação Global", f"{ocup_global_pct:.1f}%")
            
            df_balanco = df_balanco.sort_values('ocupacao_pct', ascending=False)
            
            # --- MONTANDO O GRÁFICO COM AS BARRAS EMPILHADAS ---
            fig_bal = go.Figure()
            
            # COLUNA 1: A Régua de Capacidade (Verde Escuro + Verde Claro)
            fig_bal.add_trace(go.Bar(x=df_balanco['linha'], y=df_balanco['capacidade_h'], name='Capacidade Líquida', marker_color='#28a745', offsetgroup=0))
            fig_bal.add_trace(go.Bar(x=df_balanco['linha'], y=df_balanco['banco_horas'], name='Folga / BH', marker_color='#85e0a3', offsetgroup=0, base=df_balanco['capacidade_h']))
            
            # COLUNA 2: A Demanda Planejada (Azul)
            fig_bal.add_trace(go.Bar(x=df_balanco['linha'], y=df_balanco['horas_planejadas'], name='Demanda Planejada', marker_color='#004a99', offsetgroup=1, base=0))
            
            fig_bal.update_layout(barmode='group', title="Gargalos e Ociosidade por Setor", yaxis_title="Horas", height=350, margin=dict(t=30, b=10))
            st.plotly_chart(fig_bal, width="stretch", key="bar_balanco_capacidade")
            
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
                st.plotly_chart(fig_ad, width="stretch", key="bar_aderencia_plan_final")
                
                with st.expander("Ver Tabela Detalhada Diária (Aderência)"):
                    df_aderencia['Desvio (h)'] = df_aderencia['horas_realizadas'] - df_aderencia['horas_planejadas']
                    st.dataframe(df_aderencia[['data_iso', 'nome', 'linha', 'wo', 'unidade', 'horas_planejadas', 'horas_realizadas', 'Desvio (h)']], width="stretch")
            else:
                st.info("Nenhum dado de planejamento ou apontamento para colaboradores ativos neste período.")
    else:
            st.info("Nenhum planejamento registrado para a escala selecionada.")

# ------------------------------------------
# ABA: KANBAN E TIMELINE
# ------------------------------------------
elif menu_selecionado == "🗂️ Kanban & Timeline":
    c_tit, c_btn = st.columns([4, 1])
    c_tit.markdown("## 🗂️ Kanban, Materiais e Timeline")
    
    # Botão de Sincronização Manual (Resolve o problema de atualização para outros usuários)
    st.write("")
    if c_btn.button("🔄 Sincronizar Tela", type="primary", use_container_width=True, help="Puxar as últimas alterações feitas por outros usuários."):
        st.rerun()
    
    # --- REGRA DE 30 DIAS BLINDADA (Ignora finalizados sem data) ---
    query_so_ativas = """
        SELECT DISTINCT p.so, p.customer 
        FROM projetos p
        LEFT JOIN (
            SELECT wo, MAX(data_fim) as ultima_mov
            FROM kanban_fases
            GROUP BY wo
        ) k ON p.wo = k.wo
        WHERE p.so IS NOT NULL AND TRIM(p.so) != ''
        AND (
            COALESCE(UPPER(TRIM(p.status_producao)), '') != 'FINALIZADO' 
            OR (k.ultima_mov IS NOT NULL AND k.ultima_mov >= CURRENT_DATE - INTERVAL '30 days')
        )
    """
    df_sos_ativas = pd.read_sql_query(query_so_ativas, engine)
    
    opcoes_projetos = []
    if not df_sos_ativas.empty:
        for _, r in df_sos_ativas.iterrows():
            cliente = r['customer'] if pd.notna(r['customer']) else "Sem Cliente"
            opcoes_projetos.append(f"{r['so']} - {cliente}")
    else:
        opcoes_projetos = ["- Nenhum projeto ativo -"]

    tab_kanban, tab_materiais, tab_timeline = st.tabs(["📋 Quadro Kanban", "📦 Gestão de Materiais", "📈 Linha do Tempo (Timeline)"])
    
    # ==========================================
    # GESTÃO DE MATERIAIS (FALTAS E SOBRAS)
    # ==========================================
    with tab_materiais:
        
        # --- CRIAÇÃO DAS TABELAS DE SOBRA AUTOMÁTICA ---
        try:
            cursor.execute('CREATE TABLE IF NOT EXISTS destinacoes_sobra (destinacao TEXT PRIMARY KEY)')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS materiais_sobra (
                    id SERIAL PRIMARY KEY,
                    so TEXT,
                    codigo TEXT,
                    descricao TEXT,
                    quantidade INTEGER,
                    valor NUMERIC,
                    destinacao TEXT,
                    data_registro TIMESTAMP
                )
            ''')
            # Popula algumas destinações iniciais se estiver vazio
            cursor.execute("SELECT COUNT(*) FROM destinacoes_sobra")
            if cursor.fetchone()[0] == 0:
                for d in ["Devolução Almoxarifado", "Sucata / Descarte", "Ajuste de BOM (Engenharia)"]:
                    cursor.execute("INSERT INTO destinacoes_sobra (destinacao) VALUES (%s)", (d,))
            conn.commit()
        except Exception:
            conn.rollback()
        # ----------------------------------------------

        st.markdown("### 📦 Controle de Materiais: Faltas e Sobras")
        
        tab_faltas, tab_sobras = st.tabs(["⚠️ Controle de Faltas", "♻️ Apontamento de Sobras"])
        
        # ---------------------------------------------------------
        # SUB-ABA 1: FALTAS (O código atual que já funciona perfeitamente)
        # ---------------------------------------------------------
        with tab_faltas:
            st.write("Registre os materiais que travam a produção. A data de recebimento formará um marco na linha do tempo do projeto.")
            
            col_mat_esq, col_mat_dir = st.columns([1, 2.5])
            
            with col_mat_esq:
                with st.container(border=True):
                    st.markdown("#### ➕ Apontar Nova Falta")
                    
                    with st.form("form_novo_material", clear_on_submit=True):
                        projeto_selecionado = st.selectbox("Sales Order (SO) / Cliente*", opcoes_projetos)
                        cod_mat = st.text_input("Código do Material*")
                        desc_mat = st.text_area("Descrição do Material*")
                        qtd_mat = st.number_input("Quantidade*", min_value=1, step=1)
                        dt_prev = st.date_input("Data Prevista de Chegada (Opcional)", value=None, format="DD/MM/YYYY")
                        
                        submit_mat = st.form_submit_button("💾 Registrar Falta", type="primary", use_container_width=True)
                        
                        if submit_mat:
                            if not cod_mat or not desc_mat or qtd_mat <= 0 or projeto_selecionado == "- Nenhum projeto ativo -":
                                st.error("❌ Projeto, Código, Descrição e Quantidade são obrigatórios!")
                            else:
                                so_extraida = projeto_selecionado.split(" - ")[0].strip()
                                dt_prev_str = dt_prev.strftime('%Y-%m-%d') if dt_prev else None
                                
                                cursor.execute("""
                                    INSERT INTO kanban_materiais (wo, codigo, descricao, quantidade, data_apontamento, data_prevista_chegada, status)
                                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo', %s, 'Faltante')
                                """, (so_extraida, cod_mat.strip(), desc_mat.strip(), qtd_mat, dt_prev_str))
                                conn.commit()
                                st.success("✔️ Material registrado como faltante na SO!")
                                time_sys.sleep(1.5)
                                st.rerun()

            with col_mat_dir:
                st.markdown("#### ⏳ Materiais Aguardando Recebimento")
                
                df_mats = pd.read_sql_query("""
                    SELECT m.id, m.wo as so_vinculada, m.codigo, m.descricao, m.quantidade, m.data_prevista_chegada,
                           p.customer as so_customer
                    FROM kanban_materiais m
                    LEFT JOIN (SELECT DISTINCT so, customer FROM projetos WHERE so IS NOT NULL) p ON m.wo = p.so
                    WHERE m.status = 'Faltante'
                """, engine)
                
                if not df_mats.empty:
                    sos_faltantes = df_mats['so_vinculada'].unique()
                    num_cols_per_row = 3
                    
                    for i in range(0, len(sos_faltantes), num_cols_per_row):
                        cols_projetos = st.columns(num_cols_per_row)
                        for j in range(num_cols_per_row):
                            if i + j < len(sos_faltantes):
                                so_falta = sos_faltantes[i + j]
                                df_mats_so = df_mats[df_mats['so_vinculada'] == so_falta]
                                
                                cliente_nome = df_mats_so['so_customer'].iloc[0] if pd.notna(df_mats_so['so_customer'].iloc[0]) else ""
                                if cliente_nome:
                                    cliente_abrev = (cliente_nome[:20] + '...') if len(cliente_nome) > 20 else cliente_nome
                                    titulo_cabecalho = f"SO: {so_falta}<br><span style='font-size: 11px; font-weight: normal;'>{cliente_abrev}</span>"
                                else:
                                    titulo_cabecalho = f"SO: {so_falta}"
                                
                                with cols_projetos[j]:
                                    st.markdown(f"<div style='text-align: center; background-color: #f8d7da; color: #721c24; padding: 6px; border-radius: 5px; margin-bottom: 10px; font-weight: bold; border: 1px solid #f5c6cb;'>{titulo_cabecalho}</div>", unsafe_allow_html=True)
                                    
                                    for _, row in df_mats_so.iterrows():
                                        with st.container(border=True):
                                            st.markdown(f"**Cód:** `{row['codigo']}`")
                                            st.markdown(f"<span style='font-size: 14px;'>{row['descricao']}</span>", unsafe_allow_html=True)
                                            st.write(f"**Qtd:** {row['quantidade']} un")
                                            prev = pd.to_datetime(row['data_prevista_chegada']).strftime('%d/%m/%Y') if pd.notna(row['data_prevista_chegada']) else "Não informada"
                                            st.caption(f"📅 *Previsão: {prev}*")
                                            
                                            c_b1, c_b2 = st.columns(2)
                                            if c_b1.button("📦 Baixa", key=f"rec_mat_{row['id']}", type="primary", use_container_width=True):
                                                cursor.execute("UPDATE kanban_materiais SET status = 'Recebido', data_recebimento = CURRENT_DATE AT TIME ZONE 'America/Sao_Paulo' WHERE id = %s", (row['id'],))
                                                conn.commit()
                                                st.rerun()
                                                
                                            if c_b2.button("🗑️ Excluir", key=f"del_mat_{row['id']}", use_container_width=True):
                                                cursor.execute("DELETE FROM kanban_materiais WHERE id = %s", (row['id'],))
                                                conn.commit()
                                                st.rerun()
                else:
                    st.info("🎉 Nenhum material faltante no momento.")

        # ---------------------------------------------------------
        # SUB-ABA 2: SOBRAS (O Novo Relatório de Controle de Custo)
        # ---------------------------------------------------------
        with tab_sobras:
            st.write("Registre os materiais excedentes durante a montagem para rastreio de custo e reavaliação de engenharia.")
            
            df_sobras = pd.read_sql_query("""
                SELECT s.id, s.so, s.codigo, s.descricao, s.quantidade, s.valor, s.destinacao, s.data_registro,
                       p.customer as so_customer
                FROM materiais_sobra s
                LEFT JOIN (SELECT DISTINCT so, customer FROM projetos WHERE so IS NOT NULL) p ON s.so = p.so
                ORDER BY s.data_registro DESC
            """, engine)
            
            col_sob_esq, col_sob_dir = st.columns([1, 2.5])
            
            with col_sob_esq:
                with st.container(border=True):
                    st.markdown("#### ➕ Apontar Sobra")
                    
                    df_destinacoes = pd.read_sql_query("SELECT destinacao FROM destinacoes_sobra", engine)
                    lista_destinacoes = df_destinacoes['destinacao'].tolist() if not df_destinacoes.empty else ["- Cadastre na Manutenção -"]
                    
                    with st.form("form_nova_sobra", clear_on_submit=True):
                        projeto_sel_sobra = st.selectbox("Sales Order (SO) / Cliente*", opcoes_projetos)
                        cod_sobra = st.text_input("Código do Material*")
                        desc_sobra = st.text_area("Descrição do Material*")
                        
                        c_qtd, c_val = st.columns(2)
                        qtd_sobra = c_qtd.number_input("Quantidade*", min_value=1, step=1)
                        # ATUALIZADO: "Valor Unitário" ao invés de "Total"
                        val_sobra = c_val.number_input("Valor Unitário (R$)*", min_value=0.01, step=10.0)
                        
                        dest_sobra = st.selectbox("Destinação / Justificativa*", ["- Selecione -"] + lista_destinacoes)
                        
                        submit_sobra = st.form_submit_button("💾 Registrar Sobra", type="primary", use_container_width=True)
                        
                        if submit_sobra:
                            if not cod_sobra or not desc_sobra or qtd_sobra <= 0 or val_sobra <= 0 or projeto_sel_sobra == "- Nenhum projeto ativo -" or dest_sobra == "- Selecione -":
                                st.error("❌ Preencha todos os campos obrigatórios (Quantidade e Valor devem ser maiores que zero)!")
                            else:
                                so_ext_sobra = projeto_sel_sobra.split(" - ")[0].strip()
                                
                                cursor.execute("""
                                    INSERT INTO materiais_sobra (so, codigo, descricao, quantidade, valor, destinacao, data_registro)
                                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo')
                                """, (so_ext_sobra, cod_sobra.strip(), desc_sobra.strip(), qtd_sobra, val_sobra, dest_sobra))
                                conn.commit()
                                st.success("✔️ Sobra de material registrada com sucesso!")
                                time_sys.sleep(1.5)
                                st.rerun()

                st.write("")
                with st.expander("✏️ Editar ou Excluir Apontamento de Sobra"):
                    if not df_sobras.empty:
                        df_sos_com_sobra = df_sobras[['so', 'so_customer']].drop_duplicates()
                        lista_sos_edit = ["- Selecione o Projeto -"] + sorted([f"{r['so']} - {r['so_customer'] if pd.notna(r['so_customer']) else 'Sem Cliente'}" for _, r in df_sos_com_sobra.iterrows()])
                        
                        so_edit_sel = st.selectbox("1. Selecione o Projeto (SO):", lista_sos_edit, key="so_edit_sobra_sel")
                        
                        if so_edit_sel != "- Selecione o Projeto -":
                            so_clean_edit = so_edit_sel.split(" - ")[0].strip()
                            df_sobras_filtro = df_sobras[df_sobras['so'] == so_clean_edit]
                            
                            sobra_edit_list = ["- Selecione o Material -"] + [f"ID {r['id']} | Cód: {r['codigo']} - {r['descricao'][:30]}..." for _, r in df_sobras_filtro.iterrows()]
                            sobra_selecionada = st.selectbox("2. Selecione o registro:", sobra_edit_list, key="item_edit_sobra_sel")
                            
                            if sobra_selecionada != "- Selecione o Material -":
                                id_edit = sobra_selecionada.split(" | ")[0].replace("ID ", "")
                                row_sobra = df_sobras_filtro[df_sobras_filtro['id'].astype(str) == id_edit].iloc[0]
                                
                                st.write("**3. Altere os dados abaixo:**")
                                
                                c_e1, c_e2 = st.columns(2)
                                edit_cod = c_e1.text_input("Código do Material", value=row_sobra['codigo'], key="ed_cod_sobra")
                                edit_qtd = c_e2.number_input("Quantidade", value=int(row_sobra['quantidade']), min_value=1, step=1, key="ed_qtd_sobra")
                                
                                edit_desc = st.text_area("Descrição", value=row_sobra['descricao'], key="ed_desc_sobra")
                                
                                df_dest_edit = pd.read_sql_query("SELECT destinacao FROM destinacoes_sobra", engine)
                                list_dest_edit = df_dest_edit['destinacao'].tolist() if not df_dest_edit.empty else ["- Vazio -"]
                                
                                try:
                                    idx_dest = list_dest_edit.index(row_sobra['destinacao'])
                                except ValueError:
                                    idx_dest = 0
                                    
                                c_e3, c_e4 = st.columns(2)
                                # ATUALIZADO: "Valor Unitário"
                                edit_val = c_e3.number_input("Valor Unitário (R$)", value=float(row_sobra['valor']), min_value=0.0, step=10.0, key="ed_val_sobra")
                                edit_dest = c_e4.selectbox("Destinação", list_dest_edit, index=idx_dest, key="ed_dest_sobra")
                                
                                st.write("")
                                c_btn_e1, c_btn_e2 = st.columns([1, 1])
                                
                                if c_btn_e1.button("💾 Salvar Alterações", type="primary", use_container_width=True):
                                    if not edit_cod or not edit_desc:
                                        st.error("O Código e a Descrição não podem ficar em branco.")
                                    else:
                                        cursor.execute("""
                                            UPDATE materiais_sobra 
                                            SET codigo=%s, descricao=%s, quantidade=%s, valor=%s, destinacao=%s 
                                            WHERE id=%s
                                        """, (edit_cod.strip(), edit_desc.strip(), edit_qtd, edit_val, edit_dest, id_edit))
                                        conn.commit()
                                        st.success("✔️ Registro atualizado com sucesso!")
                                        time_sys.sleep(1.5)
                                        st.rerun()
                                        
                                if c_btn_e2.button("🗑️ Excluir Registro", use_container_width=True):
                                    cursor.execute("DELETE FROM materiais_sobra WHERE id=%s", (id_edit,))
                                    conn.commit()
                                    st.success("✔️ Registro excluído!")
                                    time_sys.sleep(1.5)
                                    st.rerun()
                    else:
                        st.info("Nenhuma sobra para editar.")

            with col_sob_dir:
                st.markdown("#### 📊 Extrato de Sobras (Custos e Destinação)")
                
                if not df_sobras.empty:
                    # 1. PREPARAÇÃO E CÁLCULO DO VALOR TOTAL
                    df_sobras['valor_unit_num'] = pd.to_numeric(df_sobras['valor'], errors='coerce').fillna(0)
                    df_sobras['quantidade_num'] = pd.to_numeric(df_sobras['quantidade'], errors='coerce').fillna(0)
                    df_sobras['valor_total_calc'] = df_sobras['quantidade_num'] * df_sobras['valor_unit_num']
                    df_sobras['mes_ano'] = pd.to_datetime(df_sobras['data_registro']).dt.strftime('%m/%Y')
                    
                    # 2. FILTROS INTERATIVOS DE TELA
                    meses_disp = ["- Todos os Meses -"] + sorted(df_sobras['mes_ano'].unique().tolist(), reverse=True)
                    projetos_disp = ["- Todos os Projetos -"] + sorted(df_sobras['so'].unique().tolist())
                    
                    cf1, cf2 = st.columns(2)
                    filtro_mes = cf1.selectbox("📅 Filtrar por Mês:", meses_disp, key="filtro_mes_sobra_geral")
                    filtro_proj = cf2.selectbox("📁 Filtrar por Projeto:", projetos_disp, key="filtro_proj_sobra_geral")
                    
                    # Aplica os filtros na tabela e gráficos
                    df_sobras_filt = df_sobras.copy()
                    if filtro_mes != "- Todos os Meses -":
                        df_sobras_filt = df_sobras_filt[df_sobras_filt['mes_ano'] == filtro_mes]
                    if filtro_proj != "- Todos os Projetos -":
                        df_sobras_filt = df_sobras_filt[df_sobras_filt['so'] == filtro_proj]

                    if not df_sobras_filt.empty:
                        # --- GRÁFICOS ATUALIZADOS ---
                        cg1, cg2 = st.columns(2)
                        
                        with cg1:
                            df_graf_so = df_sobras_filt.groupby('so')['valor_total_calc'].sum().reset_index()
                            df_graf_so = df_graf_so.sort_values(by='valor_total_calc', ascending=True).tail(10)
                            df_graf_so['valor_str'] = df_graf_so['valor_total_calc'].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                            
                            fig_so = px.bar(df_graf_so, x='valor_total_calc', y='so', orientation='h', 
                                            title="Top 10 Projetos (Custo Total R$)",
                                            text='valor_str',
                                            color_discrete_sequence=['#dc3545'])
                            
                            fig_so.update_traces(textposition='auto', textfont=dict(color='white' if len(df_graf_so) > 0 else 'black'))
                            fig_so.update_layout(height=280, margin=dict(l=10, r=20, t=30, b=10), xaxis=dict(showticklabels=False, title=""), yaxis=dict(title=""))
                            st.plotly_chart(fig_so, use_container_width=True)
                            
                        with cg2:
                            df_graf_dest = df_sobras_filt.groupby('destinacao')['valor_total_calc'].sum().reset_index()
                            
                            fig_dest = px.pie(df_graf_dest, names='destinacao', values='valor_total_calc', hole=0.45, 
                                              title="Proporção Financeira por Destinação",
                                              color_discrete_sequence=px.colors.qualitative.Pastel)
                            
                            fig_dest.update_traces(textinfo='percent', textposition='inside', insidetextorientation='radial')
                            fig_dest.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), 
                                                   legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5))
                            st.plotly_chart(fig_dest, use_container_width=True)
                        
                        st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px;'>", unsafe_allow_html=True)
                        
                        # --- TABELA CORRIGIDA (Unitário e Total) ---
                        df_sobras_view = df_sobras_filt.copy()
                        df_sobras_view['data_registro'] = pd.to_datetime(df_sobras_view['data_registro']).dt.strftime('%d/%m/%Y')
                        
                        df_sobras_view['v_unit_str'] = df_sobras_view['valor_unit_num'].apply(lambda x: f"R$ {float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                        df_sobras_view['v_total_str'] = df_sobras_view['valor_total_calc'].apply(lambda x: f"R$ {float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                        
                        cols_rename = {
                            'so': 'SO', 'so_customer': 'Cliente', 'codigo': 'Código', 'descricao': 'Descrição',
                            'quantidade': 'Qtd', 'v_unit_str': 'V. Unitário', 'v_total_str': 'Custo Total', 
                            'destinacao': 'Destinação', 'data_registro': 'Data'
                        }
                        
                        st.dataframe(df_sobras_view[['so', 'so_customer', 'codigo', 'descricao', 'quantidade', 'v_unit_str', 'v_total_str', 'destinacao', 'data_registro']].rename(columns=cols_rename), width="stretch", hide_index=True)
                    else:
                        st.warning("Nenhum dado encontrado para os filtros aplicados.")
                else:
                    st.info("Nenhuma sobra de material registrada até o momento.")
    # ==========================================
    # KANBAN VISUAL E MARCOS
    # ==========================================
    with tab_kanban:
        st.markdown("### 📋 Gestão Visual de Fluxo e Marcos")
        
        # --- ATUALIZADO: "Solicitação de embalagem" removida ---
        fases_eng = ["Desenhos do barramento", "Projeto Elétrico", "Lista de Fiação", "Projeto Mecânico", "Separação de Material"]
        fases_fab = ["Produção do Barramento", "Impressão de identificadores", "Montagem Mecânica", "Montagem Elétrica", "Testes", "DESINTERLIGAÇÃO/LIMPEZA", "Embalagem"]
        
        df_proj = pd.read_sql_query("SELECT nome, especialidade FROM projetistas", engine)
        lista_responsaveis = ["- Selecione -"] + [f"{r['nome']} ({r['especialidade']})" for _, r in df_proj.iterrows()]

        # ---------------------------------------------------------
        # QUADRO 1: ENGENHARIA (Orientado a SO e Entregas)
        # ---------------------------------------------------------
        st.markdown("#### ⚙️ Marcos de Engenharia e Logística")
        with st.expander("➕ Criar Cartão Kanban (Engenharia)", expanded=False):
            
            df_sos_eng = pd.read_sql_query("""
                SELECT DISTINCT p.so, p.customer 
                FROM projetos p
                LEFT JOIN (
                    SELECT wo, MAX(data_fim) as ultima_mov
                    FROM kanban_fases
                    GROUP BY wo
                ) k ON p.wo = k.wo
                WHERE p.so IS NOT NULL AND TRIM(p.so) != ''
                AND (
                    COALESCE(UPPER(TRIM(p.status_producao)), '') != 'FINALIZADO' 
                    OR (k.ultima_mov IS NOT NULL AND k.ultima_mov >= CURRENT_DATE - INTERVAL '30 days')
                )
            """, engine)
            
            opcoes_projetos_eng = ["- Selecione o Projeto -"] + [f"{r['so']} - {r['customer'] if pd.notna(r['customer']) else 'Sem Cliente'}" for _, r in df_sos_eng.iterrows()]
            
            ce1, ce2, ce3, ce4 = st.columns(4)
            so_k_sel = ce1.selectbox("Projeto (SO) / Cliente:", opcoes_projetos_eng, key="so_start_k")
            fase_eng_sel = ce2.selectbox("Fase / Marco:", ["- Selecione -"] + fases_eng, key="fase_eng_start_k")
            resp_eng_sel = ce3.selectbox("Responsável:", lista_responsaveis, key="resp_eng_start_k")
            data_prev_eng = ce4.date_input("Previsão de Entrega:", date.today() + timedelta(days=5), format="DD/MM/YYYY", key="prev_eng_start_k")

            if st.button("✅ Criar Cartão Kanban", type="primary", use_container_width=True):
                if fase_eng_sel != "- Selecione -" and so_k_sel != "- Selecione o Projeto -" and resp_eng_sel != "- Selecione -":
                    so_limpa = so_k_sel.split(" - ")[0].strip()
                    resp_limpo = resp_eng_sel.split(" (")[0]
                    
                    cursor.execute("""
                        INSERT INTO kanban_fases (so, categoria, fase, responsavel, data_inicio, data_prevista, status)
                        VALUES (%s, 'Engenharia', %s, %s, CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo', %s, 'Em Andamento')
                    """, (so_limpa, fase_eng_sel, resp_limpo, data_prev_eng.strftime('%Y-%m-%d')))
                    conn.commit()
                    st.success(f"✔️ Cartão de {fase_eng_sel} criado para a SO {so_limpa}!")
                    time_sys.sleep(1.5); st.rerun()
                else:
                    st.error("Preencha o Projeto, Fase e Responsável para iniciar.")
        
        df_kanban_eng = pd.read_sql_query("""
            SELECT k.id, k.so, k.fase, k.responsavel, k.data_inicio, k.data_prevista,
                   p_so.customer as so_customer
            FROM kanban_fases k
            LEFT JOIN (SELECT DISTINCT so, customer FROM projetos WHERE so IS NOT NULL) p_so ON k.so = p_so.so
            WHERE k.data_fim IS NULL AND k.status = 'Em Andamento' AND k.categoria = 'Engenharia'
        """, engine)

        cols_eng = st.columns(len(fases_eng))
        for i, fase_nome in enumerate(fases_eng):
            with cols_eng[i]:
                st.markdown(f"<div style='text-align: center; background-color: #004a99; color: white; padding: 5px; border-radius: 5px; margin-bottom: 10px; font-weight: bold; font-size: 14px;'>{fase_nome}</div>", unsafe_allow_html=True)
                df_fase = df_kanban_eng[df_kanban_eng['fase'] == fase_nome]
                for _, row in df_fase.iterrows():
                    with st.container(border=True):
                        st.markdown(f"<h5 style='margin-bottom:0px; color:#004a99;'>SO: {row['so']}</h5>", unsafe_allow_html=True)
                        cliente_nome = row['so_customer'] if pd.notna(row['so_customer']) else "Desconhecido"
                        st.caption(f"{cliente_nome}")
                        st.write(f"👤 **Resp:** {row['responsavel']}")
                        d_prev = pd.to_datetime(row['data_prevista']).strftime('%d/%m/%Y') if pd.notna(row['data_prevista']) else "Não definida"
                        st.write(f"🎯 **Previsão:** {d_prev}")
                        
                        if st.button("🏁 Finalizar Entrega", key=f"fin_eng_{row['id']}", use_container_width=True):
                            cursor.execute("UPDATE kanban_fases SET data_fim = CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo', status = 'Concluído' WHERE id = %s", (row['id'],))
                            conn.commit()
                            st.success("Marco concluído e enviado para a Timeline!")
                            time_sys.sleep(1); st.rerun()

        st.markdown("<br><hr>", unsafe_allow_html=True)

        # ---------------------------------------------------------
        # QUADRO 2: FÁBRICA (Orientado a WO, Status Global e Fluxo)
        # ---------------------------------------------------------
        st.markdown("#### 🏭 Fluxo de Fábrica (Por WO)")
        with st.expander("➕ Criar Cartão Kanban (Fábrica)", expanded=False):
            tipo_cartao = st.radio("Tipo de Cartão:", ["Vinculado a Projeto (SO/WO)", "Atividade Avulsa (Genérica)"], horizontal=True)
            
            if tipo_cartao == "Vinculado a Projeto (SO/WO)":
                col_f1, col_f2, col_f3 = st.columns(3)
                
                so_fab_sel = col_f1.selectbox("1. Projeto (SO):", opcoes_projetos, key="so_fab_sel_k")
                
                if so_fab_sel != "- Nenhum projeto ativo -":
                    so_clean_fab = so_fab_sel.split(" - ")[0].strip()
                    df_wos_fab = pd.read_sql_query(f"SELECT wo, product_name, status_producao FROM projetos WHERE so = '{so_clean_fab}'", engine)
                    lista_wos_fab = ["- Selecione a WO -"] + [f"{r['wo']} - {r['product_name']} ({r['status_producao']})" for _, r in df_wos_fab.iterrows()]
                else:
                    lista_wos_fab = ["- Aguardando Projeto -"]
                    so_clean_fab = None
                    
                wo_fab_sel = col_f2.selectbox("2. Ordem de Produção (WO):", lista_wos_fab, key="wo_fab_sel_k")
                fase_fab_sel = col_f3.selectbox("3. Fase do Setor:", ["- Selecione -"] + fases_fab, key="fase_fab_start_k")
                
                if st.button("➕ Criar Cartão Kanban", type="primary", use_container_width=True):
                    if so_fab_sel != "- Nenhum projeto ativo -" and wo_fab_sel != "- Selecione a WO -" and wo_fab_sel != "- Aguardando Projeto -" and fase_fab_sel != "- Selecione -":
                        wo_clean_fab = wo_fab_sel.split(" - ")[0].strip()
                        
                        # --- INSERÇÃO INICIAL COM STATUS ADEQUADO ---
                        status_inicial = "Aguardando Embalagem" if fase_fab_sel == "Embalagem" else "Não Iniciado"
                        
                        cursor.execute("""
                            INSERT INTO kanban_fases (so, wo, categoria, fase, responsavel, status)
                            VALUES (%s, %s, 'Fábrica', %s, 'Equipe de Fábrica', %s)
                        """, (so_clean_fab, wo_clean_fab, fase_fab_sel, status_inicial))
                        conn.commit()
                        
                        st.success(f"✔️ Cartão Kanban criado na fase {fase_fab_sel}!")
                        time_sys.sleep(1.5); st.rerun()
                    else:
                        st.error("Preencha todos os campos para criar o cartão.")
                        
            else: 
                col_a1, col_a2, col_a3 = st.columns(3)
                so_avulsa_sel = col_a1.selectbox("1. Projeto (SO):", opcoes_projetos, key="so_avulsa_start_k")
                wo_avulsa_txt = col_a2.text_input("2. Identificação / Cartão:", key="wo_avulsa_txt")
                fase_avulsa_sel = col_a3.selectbox("3. Fase do Setor:", ["- Selecione -"] + fases_fab, key="fase_avulsa_start_k")
                
                if st.button("➕ Criar Cartão Kanban (Avulso)", type="primary", use_container_width=True):
                    if so_avulsa_sel != "- Nenhum projeto ativo -" and wo_avulsa_txt.strip() and fase_avulsa_sel != "- Selecione -":
                        so_limpa = so_avulsa_sel.split(" - ")[0].strip()
                        
                        status_inicial = "Aguardando Embalagem" if fase_avulsa_sel == "Embalagem" else "Não Iniciado"
                        
                        cursor.execute("""
                            INSERT INTO kanban_fases (so, wo, categoria, fase, responsavel, status)
                            VALUES (%s, %s, 'Fábrica', %s, 'Equipe de Fábrica', %s)
                        """, (so_limpa, wo_avulsa_txt.strip(), fase_avulsa_sel, status_inicial))
                        conn.commit()
                        st.success("Cartão avulso criado e vinculado à SO com sucesso!")
                        time_sys.sleep(1.5); st.rerun()
                    else:
                        st.error("Preencha o Projeto, a Identificação e a Fase.")

        df_kanban_fab = pd.read_sql_query("""
            SELECT k.id, k.so, k.wo, k.fase, k.responsavel, k.data_inicio, k.status as card_status,
                   p_wo.product_name as wo_product, p_wo.status_producao as wo_status,
                   p_so.customer as so_customer
            FROM kanban_fases k
            LEFT JOIN (SELECT DISTINCT wo, product_name, status_producao FROM projetos WHERE wo IS NOT NULL) p_wo ON k.wo = p_wo.wo
            LEFT JOIN (SELECT DISTINCT so, customer FROM projetos WHERE so IS NOT NULL) p_so ON k.so = p_so.so
            WHERE k.data_fim IS NULL AND k.status != 'Concluído' AND k.categoria = 'Fábrica'
        """, engine)

        cols_fab = st.columns(len(fases_fab))
        for i, fase_nome in enumerate(fases_fab):
            with cols_fab[i]:
                st.markdown(f"<div style='text-align: center; background-color: #28a745; color: white; padding: 5px; border-radius: 5px; margin-bottom: 10px; font-weight: bold; font-size: 14px;'>{fase_nome}</div>", unsafe_allow_html=True)
                
                df_fase = df_kanban_fab[df_kanban_fab['fase'] == fase_nome]
                for _, row in df_fase.iterrows():
                    with st.container(border=True):
                        st.markdown(f"<h5 style='margin-bottom:0px; color:#28a745;'>{row['wo']}</h5>", unsafe_allow_html=True)
                        
                        if row['so'] and row['so'] != 'AVULSO':
                            cliente_nome = row['so_customer'] if pd.notna(row['so_customer']) else ""
                            if cliente_nome:
                                cliente_abrev = (cliente_nome[:18] + '...') if len(cliente_nome) > 18 else cliente_nome
                                st.markdown(f"**Projeto:** {row['so']} - {cliente_abrev}")
                            else:
                                st.markdown(f"**Projeto:** {row['so']}")
                        
                        prod_nome = row['wo_product'] if pd.notna(row['wo_product']) else "Atividade Avulsa"
                        st.caption(f"{prod_nome}")
                        
                        # --- CORES DOS STATUS ATUALIZADAS (Amarelo para Espera) ---
                        status_c = row['card_status']
                        if status_c in ['Não Iniciado', 'Aguardando Embalagem']:
                            cor_card = "#6c757d" # Cinza
                        elif status_c == 'Em Andamento':
                            cor_card = "#004a99" # Azul
                        elif status_c in ['Aguardando Mecânica', 'Aguardando Elétrica']:
                            cor_card = "#ffcc00" # Amarelo escuro (Destaque visual)
                        else:
                            cor_card = "#dc3545" # Vermelho (Parada)
                            
                        st.markdown(f"**Status:** <span style='color:{cor_card}; font-weight:bold;'>{status_c}</span>", unsafe_allow_html=True)
                        
                        if pd.notna(row['data_inicio']):
                            d_ini = pd.to_datetime(row['data_inicio']).strftime('%d/%m/%Y %H:%M')
                            st.caption(f"⏳ Início: {d_ini}")
                        else:
                            st.caption("⏳ Horário não iniciado")
                        
                        # --- MENU DE AÇÕES LIMPO (Sem transição de fase) ---
                        opcoes_acao = ["- Selecione a Ação -", "▶️ Iniciar / Retomar", "⏸️ Sinalizar Parada / Espera", "✅ Finalizar Etapa", "🏁 Finalizar WO (Encerrar)", "🗑️ Excluir Cartão"]
                        acao = st.selectbox("Ações:", opcoes_acao, key=f"acao_{row['id']}", label_visibility="collapsed")
                        
                        if acao == "▶️ Iniciar / Retomar":
                            if st.button("Executar Ação", key=f"btn_ini_{row['id']}", use_container_width=True):
                                if pd.isna(row['data_inicio']):
                                    cursor.execute("UPDATE kanban_fases SET status = 'Em Andamento', data_inicio = CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo' WHERE id = %s", (row['id'],))
                                else:
                                    cursor.execute("UPDATE kanban_fases SET status = 'Em Andamento' WHERE id = %s", (row['id'],))
                                    
                                if row['so'] != 'AVULSO':
                                    cursor.execute("UPDATE projetos SET status_producao = 'Em Montagem' WHERE wo = %s", (row['wo'],))
                                conn.commit(); st.rerun()
                                
                        elif acao == "⏸️ Sinalizar Parada / Espera":
                            # Opções atualizadas para bater com a cor amarela
                            motivo = st.selectbox("Motivo:", ["Falta de Material", "Aguardando Mecânica", "Aguardando Elétrica", "Aguardando Embalagem", "Parada Geral"], key=f"motivo_{row['id']}")
                            if st.button("Confirmar", key=f"btn_par_{row['id']}", use_container_width=True):
                                
                                status_salvar = "Parado (Falta Mat.)" if motivo == "Falta de Material" else motivo
                                cursor.execute("UPDATE kanban_fases SET status = %s WHERE id = %s", (status_salvar, row['id']))
                                
                                if motivo == "Falta de Material" and row['so'] != 'AVULSO':
                                    cursor.execute("UPDATE projetos SET status_producao = 'Parado (Material)' WHERE wo = %s", (row['wo'],))
                                conn.commit(); st.rerun()
                                
                        elif acao == "✅ Finalizar Etapa":
                            if st.button("Executar Ação", key=f"btn_conc_{row['id']}", use_container_width=True):
                                cursor.execute("UPDATE kanban_fases SET data_fim = CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo', status = 'Concluído' WHERE id = %s", (row['id'],))
                                conn.commit(); st.rerun()
                                
                        elif acao == "🏁 Finalizar WO (Encerrar)":
                            if st.button("Executar Ação", key=f"btn_fin_{row['id']}", type="primary", use_container_width=True):
                                cursor.execute("UPDATE kanban_fases SET data_fim = CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo', status = 'Concluído' WHERE id = %s", (row['id'],))
                                if row['so'] != 'AVULSO':
                                    cursor.execute("UPDATE projetos SET status_producao = 'Finalizado' WHERE wo = %s", (row['wo'],))
                                conn.commit(); st.rerun()
                                
                        elif acao == "🗑️ Excluir Cartão":
                            if st.button("Confirmar Exclusão", key=f"btn_del_{row['id']}", use_container_width=True):
                                cursor.execute("DELETE FROM kanban_fases WHERE id = %s", (row['id'],))
                                conn.commit(); st.rerun()

    # ==========================================
    # TIMELINE E MARCOS DO PROJETO (Estilo Infográfico Executivo)
    # ==========================================
    with tab_timeline:
        st.markdown("### 📈 Análise de Ciclo de Vida do Projeto (Timeline Executiva)")
        st.write("Visão consolidada estilo infográfico: todos os eventos, entregas, paradas e materiais dispostos cronologicamente para apresentação gerencial.")
        
        if not df_sos_ativas.empty:
            lista_sos_tl = [f"{r['so']} - {r['customer'] if pd.notna(r['customer']) else ''}" for _, r in df_sos_ativas.iterrows()]
            so_selecionada_str = st.selectbox("🔍 Selecione o Projeto (SO):", ["- Selecione -"] + sorted(lista_sos_tl), key="so_timeline_sel")
            
            if so_selecionada_str != "- Selecione -":
                so_selecionada = so_selecionada_str.split(" - ")[0].strip()
                
                # 1. BUSCA DE DADOS KANBAN (Engenharia e Fábrica)
                df_fases_tl = pd.read_sql_query("""
                    SELECT k.fase, k.responsavel, k.categoria, k.data_inicio, k.data_fim, 
                           COALESCE(k.wo, 'Engenharia') as identificador
                    FROM kanban_fases k
                    LEFT JOIN projetos p ON k.wo = p.wo
                    WHERE k.so = %(so)s OR p.so = %(so)s
                """, engine, params={"so": so_selecionada})
                
                # 2. BUSCA DE APONTAMENTOS REAIS (Retrabalhos e Paradas)
                df_apont_tl = pd.read_sql_query("""
                    SELECT atividade as fase, operador as responsavel, tipo as categoria, 
                           data_registro, hora_inicio
                    FROM apontamentos
                    WHERE so = %(so)s AND tipo IN ('Retrabalho', 'Parada')
                """, engine, params={"so": so_selecionada})
                
                # 3. BUSCA DE MATERIAL (Marcos Logísticos)
                df_mats_tl = pd.read_sql_query("""
                    SELECT codigo, data_recebimento 
                    FROM kanban_materiais 
                    WHERE wo = %(so)s AND status = 'Recebido'
                """, engine, params={"so": so_selecionada})
                
                # --- MONTAGEM DO CONJUNTO DE EVENTOS PARA O INFOGRÁFICO ---
                eventos = []

                # Eventos do Kanban (Cria 1 ponto pro Início e 1 ponto pro Fim)
                if not df_fases_tl.empty:
                    for _, r in df_fases_tl.iterrows():
                        if pd.notna(r['data_inicio']):
                            eventos.append({
                                'Data': pd.to_datetime(r['data_inicio']),
                                'Nome': f"Início: {r['fase']}",
                                'Categoria': r['categoria'],
                                'Detalhe': f"Resp: {r['responsavel']} | Ref: {r['identificador']}",
                                'Icone': '⚙️' if r['categoria'] == 'Engenharia' else '🏭'
                            })
                        if pd.notna(r['data_fim']):
                            eventos.append({
                                'Data': pd.to_datetime(r['data_fim']),
                                'Nome': f"Conclusão: {r['fase']}",
                                'Categoria': r['categoria'],
                                'Detalhe': f"Resp: {r['responsavel']} | Ref: {r['identificador']}",
                                'Icone': '✅'
                            })

                # Eventos de Perdas (Retrabalho e Parada)
                if not df_apont_tl.empty:
                    def converter_datahora(d_str, h_str):
                        try:
                            if len(h_str.split(':')) == 2: h_str += ':00'
                            return pd.to_datetime(f"{d_str} {h_str}", format="%d/%m/%Y %H:%M:%S")
                        except: return pd.NaT

                    df_apont_tl['data_inicio'] = df_apont_tl.apply(lambda r: converter_datahora(r['data_registro'], r['hora_inicio']), axis=1)
                    for _, r in df_apont_tl.dropna(subset=['data_inicio']).iterrows():
                        eventos.append({
                            'Data': r['data_inicio'],
                            'Nome': f"{r['categoria']}: {r['fase'][:15]}...",
                            'Categoria': r['categoria'],
                            'Detalhe': f"Op: {r['responsavel']}",
                            'Icone': '⚠️' if r['categoria'] == 'Retrabalho' else '🛑'
                        })

                # Eventos Logísticos
                if not df_mats_tl.empty:
                    for _, r in df_mats_tl.iterrows():
                        if pd.notna(r['data_recebimento']):
                            eventos.append({
                                'Data': pd.to_datetime(r['data_recebimento']),
                                'Nome': f"Material Rec.",
                                'Categoria': 'Logística',
                                'Detalhe': f"Código: {r['codigo']}",
                                'Icone': '📦'
                            })

                if eventos:
                    df_ev = pd.DataFrame(eventos)
                    df_ev = df_ev.sort_values('Data').reset_index(drop=True)
                    df_ev['Data_Str'] = df_ev['Data'].dt.strftime('%d/%m/%Y %H:%M')

                    # --- CONSTRUÇÃO DO GRÁFICO (Estilo Lollipop / Pin) ---
                    fig_tl = go.Figure()

                    # 1. Linha Base Central (Eixo X visível)
                    data_min = df_ev['Data'].min() - pd.Timedelta(days=1)
                    data_max = df_ev['Data'].max() + pd.Timedelta(days=1)
                    
                    fig_tl.add_trace(go.Scatter(
                        x=[data_min, data_max], y=[0, 0],
                        mode="lines", line=dict(color="#ced4da", width=5),
                        hoverinfo="skip", showlegend=False
                    ))

                    # 2. Definição de Cores e Alturas (Staggering para não encavalar)
                    cores_map = {
                        "Engenharia": "#004a99", # Azul Escuro
                        "Fábrica": "#28a745",    # Verde
                        "Retrabalho": "#dc3545", # Vermelho
                        "Parada": "#ffc107",     # Amarelo
                        "Logística": "#17a2b8"   # Ciano
                    }
                    
                    # Alturas alternadas para os balões de texto (+ e - afastam da linha central)
                    y_levels = [1, -1, 1.5, -1.5, 0.6, -0.6, 2, -2, 1.2, -1.2]

                    # 3. Desenhando cada evento (Haste + Círculo + Texto)
                    for i, row in df_ev.iterrows():
                        y_pos = y_levels[i % len(y_levels)]
                        cor = cores_map.get(row['Categoria'], "#6c757d")

                        # Haste (linha vertical fina)
                        fig_tl.add_trace(go.Scatter(
                            x=[row['Data'], row['Data']], y=[0, y_pos],
                            mode="lines", line=dict(color=cor, width=2),
                            hoverinfo="skip", showlegend=False
                        ))

                        # Círculo com o Ícone (O Pin)
                        fig_tl.add_trace(go.Scatter(
                            x=[row['Data']], y=[y_pos],
                            mode="markers+text",
                            marker=dict(size=32, color="white", line=dict(color=cor, width=3.5)),
                            text=row['Icone'],
                            textfont=dict(size=16),
                            textposition="middle center",
                            hoverinfo="text",
                            hovertext=f"<b>{row['Data_Str']}</b><br>{row['Categoria']}<br><i>{row['Nome']}</i><br>{row['Detalhe']}",
                            showlegend=False
                        ))

                        # Texto Descritivo flutuando acima ou abaixo do Pin
                        offset = 0.35 if y_pos > 0 else -0.35
                        fig_tl.add_annotation(
                            x=row['Data'], y=y_pos + offset,
                            text=f"<b>{row['Nome']}</b><br><span style='font-size:11px;color:gray'>{row['Data_Str'][:10]}</span>",
                            showarrow=False,
                            font=dict(size=12, color="#333"),
                            align="center"
                        )

                    # 4. Adicionando botões de legenda simulados
                    for cat, cor in cores_map.items():
                        if cat in df_ev['Categoria'].values:
                            fig_tl.add_trace(go.Scatter(
                                x=[None], y=[None], mode="markers",
                                marker=dict(size=12, color=cor),
                                name=cat
                            ))

                    # 5. Layout e Acabamento Final
                    fig_tl.update_layout(
                        height=600,
                        plot_bgcolor='white',
                        margin=dict(t=30, b=50, l=20, r=20),
                        xaxis=dict(showgrid=True, gridcolor='#f8f9fa', showline=False, zeroline=False, tickformat="%d/%m\n%Y"),
                        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False, range=[-3, 3]),
                        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5, title="")
                    )

                    st.plotly_chart(fig_tl, use_container_width=True)
                    
                    with st.expander("Ver Log Tabela de Eventos"):
                        st.dataframe(df_ev[['Data_Str', 'Categoria', 'Nome', 'Detalhe']].rename(columns={'Data_Str': 'Data'}), use_container_width=True)
                else:
                    st.info("O projeto selecionado não possui eventos registrados (Kanban, Perdas ou Material).")
        else:
            st.info("Nenhuma Ordem de Venda (SO) ativa ou finalizada recentemente encontrada.")

# ------------------------------------------
# ABA: MANUTENÇÃO E IMPORTAÇÃO
# ------------------------------------------
elif menu_selecionado == "🔍 Manutenção":
    if user_role == "viewer":
        st.error("🔒 Acesso Restrito - Modo de Visualização Gerencial (Apenas Leitura)")
    else:
        st.subheader("⚙️ Manutenção de Dados Mestre")
        
        cat_manut = st.radio("Selecione a Tabela de Visualização/Edição:", [
            "Colaboradores", "Férias", "Feriados", 
            "Calendário Lucy", "Configurações (Erros e Paradas)", "Parâmetros de Jornada", 
            "Responsáveis (Projetos)", "Destinações de Sobra", 
            "Parâmetros de Custo (HH/OH)", "Itens Kanban", "Fáscias (Itens Ignorados)", "Motivos de Auditoria", # <--- AQUI
            "📥 Importação de Excel (Em Lote)"
        ], horizontal=True)
        
        with st.container(border=True):
            if cat_manut == "📥 Importação de Excel (Em Lote)":
                st.subheader("📤 Importação via Excel")
                
                # ADICIONADO: "Itens Kanban" e "Fáscias" na lista de opções
                op_c = st.selectbox("Qual tabela deseja atualizar via Excel?", [
                    "WOs/SOs", "Colaboradores", "Férias", "Calendário Lucy", 
                    "Feriados", "Tipos de Erro", "Causadores de Erro", 
                    "Itens Kanban", "Fáscias (Itens Ignorados)"
                ])
                
                guias = {
                    "WOs/SOs": ["so", "customer", "wo", "item", "product_name", "qtde", "horas_vendidas", "linha"],
                    "Colaboradores": ["matricula", "nome", "linha", "data_admissao", "data_demissao"],
                    "Férias": ["matricula", "data_inicio", "data_fim"],
                    "Calendário Lucy": ["start_date", "end_date", "std_month", "lucy_month", "week"],
                    "Feriados": ["data", "descricao"],
                    "Tipos de Erro": ["erro"],
                    "Causadores de Erro": ["causador"],
                    "Itens Kanban": ["codigo", "descricao"],             # <--- NOVA GUIA (Planilha A)
                    "Fáscias (Itens Ignorados)": ["codigo", "descricao", "motivo"] # <--- NOVA GUIA (Planilha B)
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
                if f_xlsx and st.button("🚀 EXECUTAR IMPORTAÇÃO", width="stretch"):
                    try:
                        df_up = pd.read_excel(f_xlsx)
                        
                        # Limpa espaços em branco nos nomes das colunas da planilha para evitar erros
                        df_up.columns = df_up.columns.str.strip()
                        
                        # Força o renomeio para o padrão do banco
                        df_up.columns = guias[op_c]
                        
                        if op_c in colunas_de_data:
                            df_up = formatar_datas_para_banco(df_up, colunas_de_data[op_c])
                        
                        target = {
                            "WOs/SOs": ("projetos", True), "Colaboradores": ("colaboradores", False), 
                            "Férias": ("ferias_colaboradores", False), "Calendário Lucy": ("calendario_lucy", False),
                            "Feriados": ("feriados", False), "Tipos de Erro": ("tipos_erro", False),
                            "Causadores de Erro": ("causadores_erro", False),
                            "Itens Kanban": ("itens_kanban", False),                       # <--- MAPEAR TABELA
                            "Fáscias (Itens Ignorados)": ("itens_ignorados_auditoria", False) # <--- MAPEAR TABELA
                        }
                        
                        t_name, has_status = target[op_c]
                        if has_status: df_up['status_producao'] = 'Não iniciada'
                        if op_c == "WOs/SOs": df_up['item'] = ""
                        
                        # Remove duplicatas da própria planilha antes de enviar (Previne erros do banco)
                        if op_c in ["Itens Kanban", "Fáscias (Itens Ignorados)"]:
                            df_up['codigo'] = df_up['codigo'].astype(str).str.strip()
                            df_up = df_up.drop_duplicates(subset=['codigo'])
                        
                        df_up.to_sql(t_name, engine, if_exists='append', index=False)
                        st.success(f"✔️ Carga de '{op_c}' concluída com sucesso no banco de dados!")
                        
                    except Exception as e:
                        if "UniqueViolation" in str(e) or "duplicate key" in str(e).lower():
                            st.error("❌ Erro: Você tentou importar códigos que JÁ ESTÃO cadastrados no banco de dados. O sistema bloqueou para evitar duplicatas.")
                        else:
                            st.error(f"❌ Erro na importação. Verifique se as colunas estão corretas. Detalhe técnico: {e}")

            elif cat_manut == "Parâmetros de Jornada":
                st.write("**Histórico de Vigências de Jornada**")
                df_param = pd.read_sql_query("SELECT * FROM parametros_jornada ORDER BY data_inicio DESC", engine)
                df_param = padronizar_datas_para_tela(df_param, ['data_inicio', 'data_fim'])
                st.dataframe(df_param, width="stretch")
                
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
                        if st.button("💾 Registrar Desligamento", width="stretch"):
                            cursor.execute("UPDATE colaboradores SET data_demissao = %s WHERE matricula = %s", (d_dem.strftime("%Y-%m-%d"), mat_dem.split(" - ")[0]))
                            conn.commit()
                            st.success("Desligamento registrado!"); st.rerun()
                    else:
                        st.info("Não há colaboradores ativos para desligar.")
                with c_col2:
                    st.write("**Lista Geral de Colaboradores**")
                    df_colab_view = pd.read_sql_query("SELECT * FROM colaboradores", engine)
                    df_colab_view = padronizar_datas_para_tela(df_colab_view, ['data_admissao', 'data_demissao'])
                    st.dataframe(df_colab_view, width="stretch")

            elif cat_manut == "Responsáveis (Projetos)":
                st.write("**Cadastrar Novo Responsável / Equipe**")
                with st.form("form_resp"):
                    c_r1, c_r2 = st.columns(2)
                    n_resp = c_r1.text_input("Nome do Responsável ou Equipe:")
                    n_setor = c_r2.text_input("Setor / Especialidade (Ex: Engenharia Elétrica):")
                    
                    if st.form_submit_button("💾 Salvar Responsável"):
                        if n_resp and n_setor:
                            cursor.execute("INSERT INTO projetistas (nome, especialidade) VALUES (%s, %s)", (n_resp, n_setor))
                            conn.commit()
                            st.success("Responsável cadastrado!")
                            st.rerun()
                        else:
                            st.error("Preencha o Nome e o Setor.")
                            
                st.write("**Lista de Responsáveis Atuais**")
                df_proj_view = pd.read_sql_query("SELECT id, nome as \"Responsável\", especialidade as \"Setor\" FROM projetistas ORDER BY nome", engine)
                st.dataframe(df_proj_view, width="stretch", hide_index=True)
            
            elif cat_manut == "Férias":
                c_f1, c_f2 = st.columns([1, 2])
                with c_f1:
                    st.write("**Lançar Férias**")
                    colab_df = pd.read_sql_query("SELECT matricula, nome FROM colaboradores WHERE data_demissao IS NULL OR data_demissao = ''", engine)
                    mat_f = st.selectbox("Colaborador:", [f"{r['matricula']} - {r['nome']}" for _, r in colab_df.iterrows()])
                    d_ini = st.date_input("Data de Início", date.today(), format="DD/MM/YYYY")
                    d_fim = st.date_input("Data de Fim", date.today() + timedelta(days=30), format="DD/MM/YYYY")
                    if st.button("💾 Salvar Período", width="stretch"):
                        cursor.execute("INSERT INTO ferias_colaboradores (matricula, data_inicio, data_fim) VALUES (%s,%s,%s)", (mat_f.split(" - ")[0], d_ini.strftime("%Y-%m-%d"), d_fim.strftime("%Y-%m-%d")))
                        conn.commit(); st.success("Férias registradas!"); st.rerun()
                with c_f2:
                    st.write("**Períodos Cadastrados**")
                    df_ferias_view = pd.read_sql_query("SELECT * FROM ferias_colaboradores", engine)
                    df_ferias_view = padronizar_datas_para_tela(df_ferias_view, ['data_inicio', 'data_fim'])
                    st.dataframe(df_ferias_view, width="stretch")
                    
            elif cat_manut == "Feriados":
                df_feriados_view = pd.read_sql_query("SELECT * FROM feriados", engine)
                df_feriados_view = padronizar_datas_para_tela(df_feriados_view, ['data'])
                st.dataframe(df_feriados_view, width="stretch")
                
            elif cat_manut == "Calendário Lucy":
                df_cal_view = pd.read_sql_query("SELECT * FROM calendario_lucy", engine)
                df_cal_view = padronizar_datas_para_tela(df_cal_view, ['start_date', 'end_date'])
                st.dataframe(df_cal_view, width="stretch")
                
            elif cat_manut == "Configurações (Erros e Paradas)":
                cf1, cf2, cf3 = st.columns(3)
                with cf1:
                    st.write("**Categorias de Parada**")
                    add_p = st.text_input("Nova Parada:")
                    if st.button("Salvar Parada", width="stretch") and add_p:
                        cursor.execute("INSERT INTO categorias_parada (categoria) VALUES (%s) ON CONFLICT (categoria) DO NOTHING", (add_p,))
                        conn.commit(); st.rerun()
                    st.dataframe(pd.read_sql_query("SELECT * FROM categorias_parada", engine), width="stretch")
                with cf2:
                    st.write("**Tipos de Erro**")
                    add_e = st.text_input("Novo Erro:")
                    if st.button("Salvar Erro", width="stretch") and add_e:
                        cursor.execute("INSERT INTO tipos_erro (erro) VALUES (%s) ON CONFLICT (erro) DO NOTHING", (add_e,))
                        conn.commit(); st.rerun()
                    st.dataframe(pd.read_sql_query("SELECT * FROM tipos_erro", engine), width="stretch")
                with cf3:
                    st.write("**Causadores**")
                    add_c = st.text_input("Novo Causador:")
                    if st.button("Salvar Causador", width="stretch") and add_c:
                        cursor.execute("INSERT INTO causadores_erro (causador) VALUES (%s) ON CONFLICT (causador) DO NOTHING", (add_c,))
                        conn.commit(); st.rerun()
                    st.dataframe(pd.read_sql_query("SELECT * FROM causadores_erro", engine), width="stretch")

            elif cat_manut == "Destinações de Sobra":
                st.write("**Justificativas / Destinações para Sobra de Material**")
                add_d = st.text_input("Nova Destinação:")
                if st.button("Salvar Destinação", width="stretch") and add_d:
                    cursor.execute("INSERT INTO destinacoes_sobra (destinacao) VALUES (%s) ON CONFLICT (destinacao) DO NOTHING", (add_d,))
                    conn.commit(); st.rerun()
                st.dataframe(pd.read_sql_query("SELECT destinacao as \"Destinação\" FROM destinacoes_sobra", engine), width="stretch", hide_index=True)

            # --- 1. GESTÃO DE TAXAS GLOBAIS ---
            elif cat_manut == "Parâmetros de Custo (HH/OH)":
                st.write("**Atualização de Taxas Financeiras para Auditoria**")
                
                # Lê do banco para preencher o formulário
                df_params = pd.read_sql_query("SELECT parametro, valor FROM parametros_custos", engine)
                dict_p = dict(zip(df_params['parametro'], df_params['valor']))
                
                with st.form("form_params"):
                    c1, c2 = st.columns(2)
                    v_hh = c1.number_input("Taxa HH (Divisor)", value=float(dict_p.get('taxa_hh', 77.17)), step=1.0)
                    v_oh = c2.number_input("Taxa OH (Multiplicador)", value=float(dict_p.get('taxa_oh', 1.7569)), step=0.1)
                    
                    if st.form_submit_button("💾 Salvar Novas Taxas", type="primary"):
                        cursor.execute("UPDATE parametros_custos SET valor = %s WHERE parametro = 'taxa_hh'", (v_hh,))
                        cursor.execute("UPDATE parametros_custos SET valor = %s WHERE parametro = 'taxa_oh'", (v_oh,))
                        conn.commit()
                        st.success("Taxas atualizadas no banco de dados!")
                        st.rerun()

            # --- 2. GESTÃO DE ITENS KANBAN ---
            elif cat_manut == "Itens Kanban":
                st.write("**Cadastro de Códigos Tratados via Kanban (Serão ignorados como Furo/Falta)**")
                with st.form("form_kbn", clear_on_submit=True):
                    c1, c2 = st.columns([1, 2])
                    cod = c1.text_input("Código do Item*")
                    desc = c2.text_input("Descrição")
                    
                    if st.form_submit_button("➕ Adicionar Item", type="primary"):
                        if cod:
                            cursor.execute("INSERT INTO itens_kanban (codigo, descricao) VALUES (%s, %s) ON CONFLICT (codigo) DO NOTHING", (cod.strip(), desc.strip()))
                            conn.commit()
                            st.success(f"Item {cod} adicionado!")
                            st.rerun()
                            
                st.write("**Itens Cadastrados:**")
                df_kbn = pd.read_sql_query("SELECT codigo as \"Código\", descricao as \"Descrição\" FROM itens_kanban ORDER BY codigo", engine)
                st.dataframe(df_kbn, width="stretch", hide_index=True)
                
                with st.expander("🗑️ Excluir Item Kanban"):
                    del_kbn = st.selectbox("Selecione para excluir:", ["- Selecione -"] + df_kbn['Código'].tolist() if not df_kbn.empty else ["- Vazio -"])
                    if st.button("Confirmar Exclusão") and del_kbn != "- Selecione -":
                        cursor.execute("DELETE FROM itens_kanban WHERE codigo = %s", (del_kbn,))
                        conn.commit(); st.rerun()

            # --- GESTÃO DE MOTIVOS DE AUDITORIA ---
            elif cat_manut == "Motivos de Auditoria":
                st.write("**Cadastro de Causas Raízes para Divergências (3-Way Match)**")
                with st.form("form_motivos_auditoria", clear_on_submit=True):
                    add_m = st.text_input("Novo Motivo/Justificativa:")
                    if st.form_submit_button("➕ Salvar Motivo", type="primary"):
                        if add_m:
                            cursor.execute("INSERT INTO motivos_auditoria (motivo) VALUES (%s) ON CONFLICT (motivo) DO NOTHING", (add_m.strip(),))
                            conn.commit()
                            st.success("✔️ Motivo cadastrado!")
                            st.rerun()
                            
                df_motivos = pd.read_sql_query("SELECT motivo as \"Motivos Cadastrados\" FROM motivos_auditoria ORDER BY motivo", engine)
                st.dataframe(df_motivos, width="stretch", hide_index=True)
                
                with st.expander("🗑️ Excluir Motivo"):
                    del_m = st.selectbox("Selecione o motivo para excluir:", ["- Selecione -"] + df_motivos['Motivos Cadastrados'].tolist() if not df_motivos.empty else ["- Vazio -"])
                    if st.button("Confirmar Exclusão") and del_m != "- Selecione -":
                        cursor.execute("DELETE FROM motivos_auditoria WHERE motivo = %s", (del_m,))
                        conn.commit(); st.rerun()

            # --- 3. GESTÃO DE FÁSCIAS / IGNORADOS ---
            elif cat_manut == "Fáscias (Itens Ignorados)":
                st.write("**Cadastro de Matérias-Primas consumidas em WOs externas (Excluídas totalmente da Auditoria)**")
                with st.form("form_fasc", clear_on_submit=True):
                    c1, c2, c3 = st.columns([1, 2, 2])
                    cod = c1.text_input("Código da Chapa/Item*")
                    desc = c2.text_input("Descrição")
                    motivo = c3.text_input("Justificativa", value="Fáscia - Consumo em WO Externa")
                    
                    if st.form_submit_button("➕ Adicionar Exceção", type="primary"):
                        if cod:
                            cursor.execute("INSERT INTO itens_ignorados_auditoria (codigo, descricao, motivo) VALUES (%s, %s, %s) ON CONFLICT (codigo) DO NOTHING", (cod.strip(), desc.strip(), motivo.strip()))
                            conn.commit()
                            st.success("Exceção adicionada com sucesso!")
                            st.rerun()
                            
                st.write("**Exceções Cadastradas:**")
                df_fasc = pd.read_sql_query("SELECT codigo as \"Código\", descricao as \"Descrição\", motivo as \"Motivo\" FROM itens_ignorados_auditoria ORDER BY codigo", engine)
                st.dataframe(df_fasc, width="stretch", hide_index=True)
                
                with st.expander("🗑️ Remover Exceção"):
                    del_fasc = st.selectbox("Selecione o código para voltar a auditar:", ["- Selecione -"] + df_fasc['Código'].tolist() if not df_fasc.empty else ["- Vazio -"])
                    if st.button("Confirmar Exclusão da Exceção") and del_fasc != "- Selecione -":
                        cursor.execute("DELETE FROM itens_ignorados_auditoria WHERE codigo = %s", (del_fasc,))
                        conn.commit(); st.rerun()
# ------------------------------------------
# ABA: RELATÓRIOS PDF 
# ------------------------------------------
elif menu_selecionado == "📑 Relatórios PDF":
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

            if st.button("⚙️ Processar e Gerar PDF", type="primary", width="stretch"):
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

                        st.download_button(label="📥 Baixar PDF do Relatório", data=pdf_bytes, file_name=f"Relatorio_Perdas_SO_{so_clean}.pdf", mime="application/pdf", width="stretch")
                        st.success("✔️ Relatório Inteligente compilado com sucesso!")

                except ImportError:
                    st.error("❌ A biblioteca FPDF não está instalada. Abra o terminal e execute: pip install fpdf")
                except Exception as e:
                    st.error(f"❌ Ocorreu um erro técnico na geração do documento: {e}")
# ------------------------------------------
# ABA: BUSINESS INTELLIGENCE (BI) EXECUTIVO
# ------------------------------------------
elif menu_selecionado == "📈 Painel Executivo (BI)":
    
    st.markdown("## 📈 Business Intelligence - Visão Executiva")
    st.write("Acompanhe o desempenho global, eficiência operacional e fluxo de valor (Kanban).")
    
    # --- FILTRO GLOBAL DO BI ---
    with st.container(border=True):
        col_f1, col_f2 = st.columns(2)
        hoje_bi = date.today()
        dt_inicio_bi = col_f1.date_input("Data Início (Análise):", hoje_bi.replace(day=1), format="DD/MM/YYYY")
        dt_fim_bi = col_f2.date_input("Data Fim (Análise):", hoje_bi, format="DD/MM/YYYY")
    
    # Busca todos os apontamentos
    query_bi = """
        SELECT a.data_registro, a.matricula, c.linha, a.tipo, a.atividade, a.tipo_erro, a.causador_erro, 
               (a.horas_normais + a.he_50 + a.he_100) as horas_totais, a.saldo_bh
        FROM apontamentos a
        LEFT JOIN colaboradores c ON a.matricula = c.matricula
    """
    df_bi_raw = pd.read_sql_query(query_bi, engine)
    
    if not df_bi_raw.empty:
        df_bi_raw['data_dt'] = pd.to_datetime(df_bi_raw['data_registro'], format='%d/%m/%Y', errors='coerce').dt.date
        df_bi = df_bi_raw[(df_bi_raw['data_dt'] >= dt_inicio_bi) & (df_bi_raw['data_dt'] <= dt_fim_bi)].copy()
        
        if not df_bi.empty:
            # --- CÁLCULO DAS MÉTRICAS GLOBAIS ---
            h_uteis = df_bi[df_bi['tipo'] == 'Produção Normal']['horas_totais'].sum()
            h_retrabalho = df_bi[df_bi['tipo'] == 'Retrabalho']['horas_totais'].sum()
            h_parada = df_bi[df_bi['tipo'] == 'Parada']['horas_totais'].sum()
            h_perdas = h_retrabalho + h_parada
            h_trabalhadas = h_uteis + h_perdas
            
            eficiencia_global = (h_uteis / h_trabalhadas * 100) if h_trabalhadas > 0 else 0.0
            taxa_retrabalho = (h_retrabalho / h_trabalhadas * 100) if h_trabalhadas > 0 else 0.0

            # --- RENDERIZAÇÃO DOS KPIs (TERMÔMETROS) ---
            st.markdown("### 🏆 KPIs Principais")
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            
            kpi1.metric("Eficiência Líquida (OEE)", f"{eficiencia_global:.1f}%", help="Percentual do tempo gasto agregando valor.")
            kpi2.metric("Tempo Útil Produzido", f"{h_uteis:.0f}h", help="Total de horas normais de produção.")
            kpi3.metric("Tempo Perdido (Custo)", f"{h_perdas:.0f}h", delta=f"{-h_perdas:.0f}h", delta_color="inverse", help="Soma de horas gastas com Retrabalho e Paradas.")
            kpi4.metric("Taxa de Retrabalho", f"{taxa_retrabalho:.1f}%", delta="Meta: < 5%", delta_color="off")
            
            st.markdown("---")
            
            # --- LINHA 1 DE GRÁFICOS: TENDÊNCIA E SETORES ---
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                st.markdown("#### 📈 Evolução Diária da Eficiência")
                df_diario = df_bi[df_bi['tipo'].isin(['Produção Normal', 'Retrabalho', 'Parada'])].groupby(['data_dt', 'tipo'])['horas_totais'].sum().unstack(fill_value=0).reset_index()
                for col in ['Produção Normal', 'Retrabalho', 'Parada']:
                    if col not in df_diario.columns: df_diario[col] = 0.0
                        
                df_diario['Total'] = df_diario['Produção Normal'] + df_diario['Retrabalho'] + df_diario['Parada']
                df_diario['Eficiencia'] = (df_diario['Produção Normal'] / df_diario['Total'] * 100).fillna(0)
                
                fig_evo = go.Figure()
                fig_evo.add_trace(go.Scatter(x=df_diario['data_dt'], y=df_diario['Eficiencia'], mode='lines+markers', name='Eficiência (%)', line=dict(color='#004a99', width=3), marker=dict(size=8)))
                fig_evo.add_hline(y=85, line_dash="dot", annotation_text="Meta (85%)", annotation_position="bottom right", line_color="#28a745")
                fig_evo.update_layout(height=350, yaxis=dict(range=[0, 105], title="Eficiência (%)"), xaxis_title="", margin=dict(t=20, b=10))
                st.plotly_chart(fig_evo, use_container_width=True)

            with col_g2:
                st.markdown("#### 🏭 Eficiência por Setor (Gargalos)")
                df_setor = df_bi[df_bi['tipo'].isin(['Produção Normal', 'Retrabalho', 'Parada'])].copy()
                df_setor['linha'] = df_setor['linha'].fillna('Não Identificado')
                df_grp_setor = df_setor.groupby(['linha', 'tipo'])['horas_totais'].sum().unstack(fill_value=0).reset_index()
                
                for col in ['Produção Normal', 'Retrabalho', 'Parada']:
                    if col not in df_grp_setor.columns: df_grp_setor[col] = 0.0
                        
                df_grp_setor['Total'] = df_grp_setor['Produção Normal'] + df_grp_setor['Retrabalho'] + df_grp_setor['Parada']
                df_grp_setor['Eficiencia'] = (df_grp_setor['Produção Normal'] / df_grp_setor['Total'] * 100).fillna(0)
                df_grp_setor = df_grp_setor[df_grp_setor['Total'] > 0].sort_values(by='Eficiencia', ascending=True)
                
                fig_setor = px.bar(df_grp_setor, x='Eficiencia', y='linha', orientation='h', text=df_grp_setor['Eficiencia'].apply(lambda x: f"{x:.1f}%"))
                fig_setor.update_traces(marker_color='#17a2b8', textposition='inside')
                fig_setor.update_layout(height=350, xaxis=dict(range=[0, 105], title="Eficiência (%)"), yaxis_title="", margin=dict(t=20, b=10))
                st.plotly_chart(fig_setor, use_container_width=True)

            st.markdown("---")
            
            # --- LINHA 2 DE GRÁFICOS: PARETO DE PERDAS ---
            st.markdown("#### 🚨 Diagrama de Pareto: Ofensores de Custo")
            col_p1, col_p2 = st.columns(2)
            
            with col_p1:
                df_pareto_parada = df_bi[df_bi['tipo'] == 'Parada'].groupby('atividade')['horas_totais'].sum().reset_index()
                if not df_pareto_parada.empty:
                    df_pareto_parada = df_pareto_parada.sort_values(by='horas_totais', ascending=False).head(7)
                    fig_par = px.bar(df_pareto_parada, x='atividade', y='horas_totais', title="Top 7 Motivos de Parada", text_auto='.1f', color_discrete_sequence=['#ffc107'])
                    fig_par.update_layout(height=350, xaxis_title="", yaxis_title="Horas Perdidas")
                    st.plotly_chart(fig_par, use_container_width=True)
                else:
                    st.info("Nenhuma parada registrada no período.")
                    
            with col_p2:
                df_ret_pareto = df_bi[df_bi['tipo'] == 'Retrabalho'].copy()
                if not df_ret_pareto.empty:
                    df_ret_pareto['ofensor'] = df_ret_pareto['causador_erro'].replace('', pd.NA).fillna(df_ret_pareto['tipo_erro']).fillna('Outros')
                    df_pareto_ret = df_ret_pareto.groupby('ofensor')['horas_totais'].sum().reset_index()
                    df_pareto_ret = df_pareto_ret.sort_values(by='horas_totais', ascending=False).head(7)
                    
                    fig_ret = px.bar(df_pareto_ret, x='ofensor', y='horas_totais', title="Top 7 Ofensores de Retrabalho", text_auto='.1f', color_discrete_sequence=['#dc3545'])
                    fig_ret.update_layout(height=350, xaxis_title="", yaxis_title="Horas Refazendo")
                    st.plotly_chart(fig_ret, use_container_width=True)
                else:
                    st.info("Nenhum retrabalho registrado no período.")

            st.markdown("---")
            
            # --- LINHA 3 DE GRÁFICOS: KANBAN E FLUXO ---
            st.markdown("#### 🗂️ Desempenho do Fluxo Kanban (Tempo e WIP)")
            col_k1, col_k2 = st.columns(2)
            
            df_kb_bi = pd.read_sql_query("SELECT fase, status, data_inicio, data_fim FROM kanban_fases WHERE categoria = 'Fábrica'", engine)
            
            if not df_kb_bi.empty:
                df_kb_bi['data_inicio'] = pd.to_datetime(df_kb_bi['data_inicio'], errors='coerce')
                df_kb_bi['data_fim'] = pd.to_datetime(df_kb_bi['data_fim'], errors='coerce')
                
                with col_k1:
                    df_wip = df_kb_bi[df_kb_bi['status'] != 'Concluído'].groupby('fase').size().reset_index(name='qtd_cartoes')
                    if not df_wip.empty:
                        fig_wip = px.bar(df_wip, x='qtd_cartoes', y='fase', orientation='h', 
                                         title="WIP: Onde estão os cartões agora?", text_auto=True, 
                                         color_discrete_sequence=['#17a2b8'])
                        fig_wip.update_layout(height=350, xaxis_title="Qtd de Ordens (WOs)", yaxis_title="")
                        st.plotly_chart(fig_wip, use_container_width=True)
                    else:
                        st.info("Nenhum cartão ativo no Kanban de Fábrica.")
                        
                with col_k2:
                    hoje_pd = pd.Timestamp.now()
                    df_kb_bi['data_fim_calc'] = df_kb_bi['data_fim'].fillna(hoje_pd)
                    df_kb_bi['dias_na_fase'] = (df_kb_bi['data_fim_calc'] - df_kb_bi['data_inicio']).dt.days
                    
                    df_cycle = df_kb_bi.groupby('fase')['dias_na_fase'].mean().reset_index()
                    if not df_cycle.empty:
                        fig_cycle = px.bar(df_cycle, x='fase', y='dias_na_fase', 
                                           title="Tempo Médio por Fase (Cycle Time em Dias)", text_auto='.1f', 
                                           color_discrete_sequence=['#6cb2eb'])
                        fig_cycle.update_layout(height=350, xaxis_title="", yaxis_title="Dias Médios")
                        st.plotly_chart(fig_cycle, use_container_width=True)
                    else:
                        st.info("Dados insuficientes para calcular o tempo de ciclo.")
            else:
                st.info("Sem dados no Kanban para análise de fluxo.")

        else:
            st.info("Nenhum apontamento produtivo encontrado para o período selecionado.")
    else:
        st.info("O banco de dados ainda não possui registros de apontamentos.")

# ------------------------------------------
# ABA: AUDITORIA 3-WAY & RELATÓRIO PDF EXECUTIVO
# ------------------------------------------
elif menu_selecionado == "📊 Auditoria BOM vs Real":
    st.markdown("## 📊 Auditoria de Custos: 3-Way Match (Engenharia vs Fábrica)")
    st.write("Compare a **BOM Inicial** (orçamento) com a **BOM Final** (revisão) e o **Consumo Real** para isolar desvios de engenharia e furos de fábrica.")

    # Puxa taxas globais do banco
    df_params = pd.read_sql_query("SELECT parametro, valor FROM parametros_custos", engine)
    dict_params = dict(zip(df_params['parametro'], df_params['valor']))
    t_hh = float(dict_params.get('taxa_hh', 77.17))
    t_oh = float(dict_params.get('taxa_oh', 1.7569))

    with st.expander("📁 1. Carregamento de Planilhas", expanded=True):
        c_up1, c_up2, c_up3 = st.columns(3)
        file_bom_ini = c_up1.file_uploader("BOM Inicial (Opcional)", type=['xlsx', 'csv'])
        file_bom_fin = c_up2.file_uploader("BOM Final / Atual*", type=['xlsx', 'csv'])
        file_real = c_up3.file_uploader("Consumo Real*", type=['xlsx', 'csv'])

        if st.button("🚀 Processar Análise de 3 Vias", type="primary", use_container_width=True):
            if not file_bom_fin or not file_real:
                st.error("❌ A BOM Final e o Consumo Real são obrigatórios para a análise.")
            else:
                with st.spinner("Analisando cruzamento de dados..."):
                    try:
                        # Leitura BOM Final
                        df_fin = pd.read_csv(file_bom_fin, sep=';', encoding='latin1') if file_bom_fin.name.endswith('.csv') else pd.read_excel(file_bom_fin)
                        df_fin.columns = df_fin.columns.str.strip()
                        if 'Cost per unit' in df_fin.columns and 'Cost price per unit' not in df_fin.columns:
                            df_fin.rename(columns={'Cost per unit': 'Cost price per unit'}, inplace=True)
                        df_fin['Item/Resource'] = df_fin['Item/Resource'].astype(str).str.strip()
                        
                        agg_fin = {'Consumption per lot size': 'sum', 'Cost price per unit': 'max', 'Description': 'first'}
                        if 'Processing method' in df_fin.columns: agg_fin['Processing method'] = 'first'
                        df_bom_f = df_fin.groupby('Item/Resource').agg(agg_fin).reset_index()

                        # Leitura BOM Inicial
                        if file_bom_ini:
                            df_ini = pd.read_csv(file_bom_ini, sep=';', encoding='latin1') if file_bom_ini.name.endswith('.csv') else pd.read_excel(file_bom_ini)
                            df_ini.columns = df_ini.columns.str.strip()
                            df_ini['Item/Resource'] = df_ini['Item/Resource'].astype(str).str.strip()
                            df_bom_i = df_ini.groupby('Item/Resource')['Consumption per lot size'].sum().reset_index().rename(columns={'Consumption per lot size': 'qtd_ini'})
                        else:
                            df_bom_i = df_bom_f[['Item/Resource']].copy()
                            df_bom_i['qtd_ini'] = df_bom_f['Consumption per lot size']

                        # Leitura Consumo Real
                        df_r = pd.read_csv(file_real, sep=';', encoding='latin1') if file_real.name.endswith('.csv') else pd.read_excel(file_real)
                        df_r.columns = df_r.columns.str.strip()
                        df_r['Item number'] = df_r['Item number'].astype(str).str.strip()
                        
                        # --- NOVIDADE: FILTRO INTELIGENTE DE DEVOLUÇÕES (RETURN LOT ID) ---
                        # Se a linha tem lote de devolução, ela é um estorno do ERP e não deve ser somada!
                        if 'Return lot ID' in df_r.columns:
                            df_r = df_r[df_r['Return lot ID'].isna() | (df_r['Return lot ID'].astype(str).str.strip() == '') | (df_r['Return lot ID'].astype(str).str.strip().str.lower() == 'nan')]
                        
                        # CORREÇÃO DO ERP: Transforma baixas de estoque negativas em consumo positivo
                        for col_num in ['Quantity', 'Financial cost amount', 'Physical cost amount']:
                            if col_num in df_r.columns:
                                df_r[col_num] = pd.to_numeric(df_r[col_num], errors='coerce').fillna(0).abs()
                        
                        if 'Physical cost amount' not in df_r.columns: 
                            df_r['Physical cost amount'] = 0.0

                        df_real_agg = df_r.groupby('Item number').agg({'Quantity': 'sum', 'Financial cost amount': 'sum', 'Physical cost amount': 'sum'}).reset_index()

                        # Carrega Listas do Banco
                        lista_ign = pd.read_sql_query("SELECT codigo FROM itens_ignorados_auditoria", engine)['codigo'].astype(str).tolist()
                        df_kbn_db = pd.read_sql_query("SELECT codigo, descricao FROM itens_kanban", engine)
                        lista_kbn = df_kbn_db['codigo'].astype(str).tolist()
                        dict_kbn = dict(zip(df_kbn_db['codigo'].astype(str), df_kbn_db['descricao'].astype(str)))

                        # Cruzamento 3-Way Match
                        df_m1 = pd.merge(df_bom_f, df_bom_i, on='Item/Resource', how='outer')
                        df_res = pd.merge(df_m1, df_real_agg, left_on='Item/Resource', right_on='Item number', how='outer', suffixes=('_bom', '_real'))
                        
                        df_res['Item'] = df_res['Item/Resource'].fillna(df_res['Item number']).astype(str).str.strip()
                        df_res['Eh_Kanban'] = df_res['Item'].isin(lista_kbn)
                        
                        def resolver_descricao(r):
                            desc = r['Description']
                            if pd.isna(desc) or str(desc).strip() in ['', 'nan', 'None', 'NaN', '0', '0.0']:
                                if r['Eh_Kanban']:
                                    desc_kbn = dict_kbn.get(r['Item'])
                                    return desc_kbn if pd.notna(desc_kbn) and str(desc_kbn).strip() != '' else "Item Kanban (S/ Desc)"
                                return "Item Extra/Fábrica"
                            return desc

                        df_res['Descrição'] = df_res.apply(resolver_descricao, axis=1)
                        
                        if 'Processing method' in df_res.columns:
                            df_res['Método'] = df_res['Processing method'].fillna("N/A").astype(str).str.upper().str.strip()
                            df_res['Método'] = df_res['Método'].replace(['', 'NAN', 'NAT', 'NONE', '0', '0.0'], 'N/A')
                        else:
                            df_res['Método'] = "N/A"
                        
                        df_res = df_res[~df_res['Item'].isin(lista_ign)].copy()
                        df_res = df_res[~df_res['Método'].isin(['PHANTOM', 'ASM-PH-WO', 'BUY-SC'])].copy()

                        for col in ['Consumption per lot size', 'qtd_ini', 'Quantity', 'Financial cost amount', 'Physical cost amount', 'Cost price per unit']:
                            if col in df_res.columns: df_res[col] = pd.to_numeric(df_res[col], errors='coerce').fillna(0).astype(float)

                        df_res['Custo Real Total'] = df_res.apply(lambda r: r['Financial cost amount'] if r['Financial cost amount'] != 0 else r['Physical cost amount'], axis=1)
                        df_res['Custo Unitário'] = df_res.apply(lambda r: abs(r['Custo Real Total'] / r['Quantity']) if r['Quantity'] != 0 else r['Cost price per unit'], axis=1)
                        
                        # --- MATEMÁTICA PURA ---
                        df_res['Desvio Engenharia'] = df_res['Consumption per lot size'] - df_res['qtd_ini']
                        df_res['Desvio Fábrica'] = df_res['Quantity'] - df_res['Consumption per lot size'] 
                        
                        # --- HIERARQUIA CORRIGIDA (Prioridade: BOM Final vs Consumo) ---
                        def classificar_status(r):
                            if r['Eh_Kanban']: return "Consumo Kanban"
                            
                            metodo = r['Método']
                            if metodo == 'N/A':
                                if r['qtd_ini'] > 0 or r['Consumption per lot size'] > 0: 
                                    return "Ignorado (Mão de Obra / Serviço)"

                            # 1. Alerta Crítico
                            if r['Consumption per lot size'] == 0 and r['Quantity'] > 0: 
                                return "Alerta: Consumido após Remoção"
                                
                            # 2. Desvios de FÁBRICA (Prioridade Absoluta)
                            if r['Desvio Fábrica'] > 0.001: 
                                return "Fábrica: Excedente Operacional"
                            if r['Desvio Fábrica'] < -0.001: 
                                return "Fábrica: Economia Operacional"
                                
                            # 3. Desvios de ENGENHARIA (Acontece APENAS se a fábrica não desviou)
                            if r['Desvio Engenharia'] > 0.001:
                                if r['qtd_ini'] == 0: return "Engenharia: Adicionado no Escopo"
                                else: return "Engenharia: Aumento de Qtd"
                            if r['Desvio Engenharia'] < -0.001:
                                if r['Consumption per lot size'] == 0: return "Engenharia: Removido do Escopo"
                                else: return "Engenharia: Redução de Qtd"
                                
                            return "Conforme"

                        df_res['Status'] = df_res.apply(classificar_status, axis=1)
                        
                        def calcular_qtd_divergencia(r):
                            if 'Engenharia' in r['Status']: return r['Desvio Engenharia']
                            if 'Fábrica' in r['Status'] or 'Alerta' in r['Status']: return r['Desvio Fábrica']
                            return 0.0

                        df_res['Qtd Divergência'] = df_res.apply(calcular_qtd_divergencia, axis=1)
                        
                        def calcular_impacto(r):
                            return r['Qtd Divergência'] * r['Custo Unitário']
                                
                        df_res['Impacto Financeiro (R$)'] = df_res.apply(calcular_impacto, axis=1)
                        df_res['Motivo'] = "Não Informado"
                        
                        st.session_state['res_audit_3way'] = df_res
                        st.session_state['nome_bom_base'] = file_bom_fin.name
                        st.success("✔️ Análise Matemática concluída!")
                    except Exception as e:
                        st.error(f"Erro ao processar planilhas: {e}")

    # --- RENDERIZAÇÃO DO DASHBOARD INTERATIVO ANTES DO PDF ---
    if 'res_audit_3way' in st.session_state:
        df_final = st.session_state['res_audit_3way']
        
        if 'Eh_Kanban' not in df_final.columns: df_final['Eh_Kanban'] = False
        if 'Qtd Divergência' not in df_final.columns: df_final['Qtd Divergência'] = 0.0
            
        st.markdown("---")
        st.markdown("### 📈 Painel Analítico de Custos (Prévia)")
        
        mask_mat = (df_final['Item'].str.upper() != 'MANUFACTURING OVERHEAD') & (df_final['Status'] != 'Ignorado (Mão de Obra / Serviço)')
        custo_total_mat = df_final[mask_mat]['Custo Real Total'].abs().sum()
        
        custo_kbn = df_final[df_final['Eh_Kanban'] == True]['Custo Real Total'].abs().sum()
        pct_kbn = (custo_kbn / custo_total_mat * 100) if custo_total_mat > 0 else 0
        
        custo_exc = df_final[df_final['Status'].isin(['Fábrica: Excedente Operacional', 'Alerta: Consumido após Remoção'])]['Impacto Financeiro (R$)'].sum()
        custo_eco = df_final[df_final['Status'] == 'Fábrica: Economia Operacional']['Impacto Financeiro (R$)'].sum()
        
        # Consolida o impacto financeiro LÍQUIDO da Engenharia (+ Adições, - Remoções)
        custo_eng_liq = df_final[df_final['Status'].str.contains('Engenharia')]['Impacto Financeiro (R$)'].sum()
        
        qtd_oh = df_final[df_final['Item'].str.upper() == 'MANUFACTURING OVERHEAD']['Consumption per lot size'].sum()
        valor_oh = qtd_oh * t_oh
        horas_totais = qtd_oh / t_hh if t_hh > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Custo Total Material", f"R$ {custo_total_mat:,.2f}")
        c2.metric("Proporção Kanban", f"R$ {custo_kbn:,.2f}", f"{pct_kbn:.1f}% do Custo Mat.", delta_color="off")
        c3.metric("Desperdício de Fábrica", f"R$ {custo_exc:,.2f}", f"Economia: R$ {custo_eco:+,.2f}", delta_color="inverse")
        c4.metric("Diverg. LÍQUIDA Engenharia", f"R$ {custo_eng_liq:+,.2f}", "Balanço: Adições vs Remoções", delta_color="off")

        df_graficos = df_final[df_final['Status'] != 'Ignorado (Mão de Obra / Serviço)'].copy()
        
        cg1, cg2 = st.columns(2)
        with cg1:
            df_pie = df_graficos.groupby('Status')['Item'].count().reset_index()
            if not df_pie.empty:
                total_itens = df_pie['Item'].sum()
                df_pie['Porcentagem'] = (df_pie['Item'] / total_itens * 100).round(1)
                df_pie['Rotulo_Personalizado'] = df_pie['Status'] + " (" + df_pie['Porcentagem'].astype(str) + "%)"
                
                fig_pie = px.pie(df_pie, names='Rotulo_Personalizado', values='Item', hole=0.45, title="Conformidade Geral de Itens")
                fig_pie.update_traces(textposition='inside', textinfo='percent')
                fig_pie.update_layout(showlegend=True, legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0, title=""), margin=dict(t=40, b=20, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            
        with cg2:
            mask_ofensores = df_graficos['Status'].str.contains('Excedente|Adicionado|Aumento|Alerta')
            df_bar = df_graficos[mask_ofensores]
            df_bar = df_bar.sort_values(by='Impacto Financeiro (R$)', ascending=True).tail(10) 
            
            if not df_bar.empty and df_bar['Impacto Financeiro (R$)'].sum() > 0:
                df_bar['Item'] = df_bar['Item'].astype(str)
                fig_bar = px.bar(df_bar, x='Impacto Financeiro (R$)', y='Item', orientation='h', title="Top 10 Itens: Ofensores Financeiros (+ Custo)", color='Status', text='Impacto Financeiro (R$)')
                fig_bar.update_traces(texttemplate='R$ %{text:,.2f}', textposition='outside')
                fig_bar.update_layout(yaxis=dict(type='category', title=""), xaxis=dict(title=""), showlegend=True, legend=dict(orientation="h", y=-0.2), margin=dict(t=40, b=10))
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("Nenhum item ofensor (aumento de custo) detectado no Top 10.")

        st.markdown("---")
        st.markdown("### 📋 Classificação de Causa Raiz (Motivo)")
        st.write("Antes de gerar o relatório, verifique as quantidades. Sinais **Positivos (+)** indicam Adição/Desperdício, Sinais **Negativos (-)** indicam Remoção/Economia.")
        
        mask_divergencias = df_final['Status'].str.contains('Fábrica:|Engenharia:|Alerta:')
        df_editavel = df_final[mask_divergencias].copy()
        
        if not df_editavel.empty:
            df_edit_display = df_editavel[['Item', 'Descrição', 'Status', 'Qtd Divergência', 'Impacto Financeiro (R$)', 'Motivo']].copy()
            df_edit_display['Impacto_Abs'] = df_edit_display['Impacto Financeiro (R$)'].abs()
            df_edit_display = df_edit_display.sort_values(by='Impacto_Abs', ascending=False).drop(columns=['Impacto_Abs'])
            
            df_motivos_db = pd.read_sql_query("SELECT motivo FROM motivos_auditoria ORDER BY motivo", engine)
            opcoes_motivo = ["Não Informado"] + df_motivos_db['motivo'].tolist() if not df_motivos_db.empty else ["Não Informado", "Scrap / Refugo", "Ajuste de Projeto"]
            
            tabela_editada = st.data_editor(
                df_edit_display,
                column_config={
                    "Item": st.column_config.TextColumn(disabled=True),
                    "Descrição": st.column_config.TextColumn(disabled=True),
                    "Status": st.column_config.TextColumn(disabled=True),
                    "Qtd Divergência": st.column_config.NumberColumn("Saldo Qtd", format="%+.2f", disabled=True),
                    "Impacto Financeiro (R$)": st.column_config.NumberColumn("Valor Diferença (R$)", format="R$ %+.2f", disabled=True), 
                    "Motivo": st.column_config.SelectboxColumn("Causa Raiz (Selecione)", options=opcoes_motivo, required=True)
                },
                use_container_width=True,
                hide_index=True,
                key="tabela_causa_raiz"
            )
            
            dict_motivos = dict(zip(tabela_editada['Item'], tabela_editada['Motivo']))
            df_final['Motivo'] = df_final['Item'].map(dict_motivos).fillna(df_final['Motivo'])
        else:
            st.info("Todos os itens estão Conformes ou são Kanban. Nenhuma classificação necessária.")

        st.markdown("---")
        st.markdown("### 💾 Salvar e Exportar Auditoria")
        col_b1, col_b2 = st.columns(2)
        
        if col_b1.button("📥 Gravar Histórico no Banco (Com Justificativas)", type="primary", use_container_width=True):
            with st.spinner("Gravando desvios e motivos..."):
                try: cursor.execute("ALTER TABLE auditoria_3vias_historico ADD COLUMN IF NOT EXISTS motivo TEXT")
                except: pass
                conn.commit()
                
                df_gravar = df_final[df_final['Status'].str.contains('Fábrica:|Engenharia:|Alerta:')]
                for _, r in df_gravar.iterrows():
                    cursor.execute("""
                        INSERT INTO auditoria_3vias_historico 
                        (data_auditoria, item, descricao, qtd_bom_inicial, qtd_bom_final, qtd_real, desvio_engenharia, desvio_fabrica, valor_impacto, status, motivo)
                        VALUES (CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        r['Item'], r['Descrição'], r['qtd_ini'], r['Consumption per lot size'], 
                        r['Quantity'], r['Desvio Engenharia'], r['Desvio Fábrica'], 
                        r['Impacto Financeiro (R$)'], r['Status'], r['Motivo']
                    ))
                conn.commit()
                st.success(f"✔️ {len(df_gravar)} desvios gravados no banco de dados!")

        if col_b2.button("📄 Gerar Relatório Executivo Oficial (PDF)", use_container_width=True):
            with st.spinner("Desenhando documento..."):
                try:
                    from reportlab.lib.pagesizes import A4
                    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
                    from reportlab.platypus import Image as RLImage
                    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                    from reportlab.lib import colors
                    from io import BytesIO
                    import matplotlib.pyplot as plt
                    import numpy as np
                    
                    pdf_buffer = BytesIO()
                    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
                    story = []
                    styles = getSampleStyleSheet()
                    title_style = ParagraphStyle(name='Title', parent=styles['Heading1'], alignment=1, spaceAfter=20, textColor=colors.HexColor("#003366"))

                    story.append(Paragraph("VALIDAÇÃO DE CONSUMO - 3 WAY MATCH", title_style))
                    story.append(Paragraph(f"<b>Emissão:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')} | <b>BOM Base:</b> {st.session_state.get('nome_bom_base', 'Desconhecido')}", styles['Normal']))
                    story.append(Spacer(1, 15))

                    story.append(Paragraph("<b>1. Resumo Executivo (KPIs)</b>", styles['Heading2']))
                    data_kpi = [
                        ["Indicador Analisado", "Valor (R$ / H)", "Detalhes / Composição"],
                        ["Manufacturing Overhead", f"R$ {valor_oh:,.2f}", f"Fator OH: {t_oh}"],
                        ["Horas Totais Plan.", f"{horas_totais:,.2f} h", f"Fator HH: {t_hh}"],
                        ["Custo Total Material", f"R$ {custo_total_mat:,.2f}", "Material Aplicado Geral"],
                        ["Custo Kanban", f"R$ {custo_kbn:,.2f}", f"{pct_kbn:.1f}% do Custo Material"],
                        ["Custo Excedente (Fábrica)", f"R$ {custo_exc:,.2f}", "Desperdício / Refugo Operacional"],
                        ["Economia (Fábrica)", f"R$ {custo_eco:+,.2f}", "Abaixo do orçado pela Engenharia"],
                        ["Diverg. Líq. Engenharia", f"R$ {custo_eng_liq:+,.2f}", "Balanço Adições vs Remoções"]
                    ]
                    
                    t_kpi = Table(data_kpi, colWidths=[160, 120, 200])
                    t_kpi.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#333333")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#fdfdfd")), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
                    story.append(t_kpi)
                    story.append(Spacer(1, 15))

                    story.append(Paragraph("<b>2. Análise Gráfica de Desvios</b>", styles['Heading2']))
                    
                    df_pdf_graf = df_graficos.copy()
                    fig_pdf, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.5), facecolor='white')
                    
                    dados_r = df_pdf_graf.groupby('Status')['Item'].count()
                    if not dados_r.empty:
                        wedges, texts, autotexts = ax1.pie(dados_r.values, autopct='%1.1f%%', startangle=140, pctdistance=0.85, colors=plt.cm.Set2.colors)
                        ax1.legend(wedges, dados_r.index, title="Status", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=7)
                        centre_circle = plt.Circle((0,0),0.50,fc='white')
                        ax1.add_artist(centre_circle)
                        ax1.set_title("Conformidade Geral", fontsize=10, pad=10)
                        
                    mask_ofensores_pdf = df_pdf_graf['Status'].str.contains('Excedente|Adicionado|Aumento|Alerta')
                    df_bar_pdf = df_pdf_graf[mask_ofensores_pdf].sort_values(by='Impacto Financeiro (R$)', ascending=True).tail(5)
                    
                    if not df_bar_pdf.empty and df_bar_pdf['Impacto Financeiro (R$)'].sum() > 0:
                        y_pos = np.arange(len(df_bar_pdf))
                        ax2.barh(y_pos, df_bar_pdf['Impacto Financeiro (R$)'], color='#dc3545')
                        ax2.set_yticks(y_pos, labels=df_bar_pdf['Item'].astype(str).tolist(), fontsize=7)
                        ax2.set_title("Top 5 Impacto Financeiro (+ Custo)", fontsize=10, pad=10)
                        ax2.spines['top'].set_visible(False)
                        ax2.spines['right'].set_visible(False)
                        for i, v in enumerate(df_bar_pdf['Impacto Financeiro (R$)']):
                            ax2.text(v + 3, i, f"{v:,.0f}", color='black', va='center', fontsize=7)
                    else:
                        ax2.text(0.5, 0.5, "Sem Ofensores de Custo\nno Top 5", ha='center', va='center')
                        ax2.axis('off')

                    fig_pdf.tight_layout()
                    buf_p = BytesIO()
                    fig_pdf.savefig(buf_p, format='png', dpi=150, bbox_inches='tight')
                    buf_p.seek(0)
                    plt.close(fig_pdf)
                    
                    story.append(RLImage(buf_p, width=480, height=210))
                    story.append(PageBreak())
                    
                    def add_tabela_pdf_motivo(df_sub, titulo):
                        if df_sub.empty: return
                        story.append(Paragraph(f"<b>Tabela: {titulo}</b>", styles['Heading3']))
                        
                        df_sub['Impacto_Abs'] = df_sub['Impacto Financeiro (R$)'].abs()
                        df_top = df_sub.sort_values(by='Impacto_Abs', ascending=False).head(20)
                        tot_val = df_sub['Impacto Financeiro (R$)'].sum()
                        
                        t_data = [["Item", "Descrição", "Saldo Qtd", "Valor Diferença (R$)", "Motivo"]]
                        for _, r in df_top.iterrows():
                            t_data.append([str(r['Item']), str(r['Descrição'])[:25], f"{r['Qtd Divergência']:+.2f}", f"R$ {r['Impacto Financeiro (R$)']:+,.2f}", str(r.get('Motivo', '-'))])
                        t_data.append(['-', 'TOTAL GERAL DA CATEGORIA', '-', f"R$ {tot_val:+,.2f}", '-'])
                        
                        t = Table(t_data, colWidths=[65, 180, 55, 80, 100])
                        t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#444444")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTSIZE', (0,0), (-1,-1), 7), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'), ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#e2e8f0"))]))
                        story.append(t)
                        story.append(Spacer(1, 15))

                    df_exc = df_final[df_final['Status'].isin(['Fábrica: Excedente Operacional', 'Alerta: Consumido após Remoção'])].copy()
                    add_tabela_pdf_motivo(df_exc, "Consumo Excedente")
                    
                    df_eco = df_final[df_final['Status'] == 'Fábrica: Economia Operacional'].copy()
                    add_tabela_pdf_motivo(df_eco, "Consumo Abaixo do Previsto")
                    
                    df_eng = df_final[df_final['Status'].str.contains('Engenharia')].copy()
                    add_tabela_pdf_motivo(df_eng, "Divergências de Engenharia (Adições e Remoções)")
                    
                    df_kbn_pdf = df_final[df_final['Status'] == 'Consumo Kanban'].sort_values(by='Custo Real Total', ascending=False).head(20)
                    if not df_kbn_pdf.empty:
                        story.append(Paragraph(f"<b>Tabela: Itens Kanban (Top 20 Custos)</b>", styles['Heading3']))
                        t_data = [["Item", "Descrição", "Qtd Consumida", "Custo Total (R$)"]]
                        for _, r in df_kbn_pdf.iterrows():
                            t_data.append([str(r['Item']), str(r['Descrição'])[:35], f"{r['Quantity']:.2f}", f"R$ {r['Custo Real Total']:,.2f}"])
                        t_data.append(['-', 'TOTAL KANBAN GERAL', '-', f"R$ {custo_kbn:,.2f}"])
                        
                        t = Table(t_data, colWidths=[70, 250, 70, 90])
                        t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#444444")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTSIZE', (0,0), (-1,-1), 8), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'), ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#e2e8f0"))]))
                        story.append(t)

                    story.append(Spacer(1, 40))
                    sig = Table([["______________________________________", "______________________________________"], ["Responsável (Preparação)", "Validação Gerencial"]], colWidths=[260, 260])
                    sig.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,-1), 10)]))
                    story.append(sig)

                    doc.build(story)
                    pdf_data = pdf_buffer.getvalue()

                    st.download_button(
                        label="📥 Baixar Relatório Executivo Zopone (PDF)",
                        data=pdf_data,
                        file_name=f"Relatorio_Auditoria_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                    st.success("✔️ Relatório PDF estruturado com sucesso nas 3 tabelas de divergência!")
                except Exception as e:
                    st.error(f"❌ Erro na geração do PDF: {e}")
# Teste de conexão com o GitHub
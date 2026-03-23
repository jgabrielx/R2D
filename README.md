# R2D — Construtor de Relatório Fotográfico

Aplicação web para geração de relatórios fotográficos no padrão R2D/Banco do Brasil.  
Inclui construtor com prévia ao vivo, geração de PDF e histórico de relatórios da equipe.

---

## Deploy no Railway (gratuito)

### Pré-requisito: conta no GitHub e no Railway

1. **Crie um repositório no GitHub**
   - Acesse github.com → New repository → nome: `r2d-relatorios` → Create
   - Faça upload de todos os arquivos desta pasta (arraste para o repositório)

2. **Conecte ao Railway**
   - Acesse railway.app → Login com GitHub
   - Clique em **New Project → Deploy from GitHub repo**
   - Selecione o repositório `r2d-relatorios`
   - Railway detecta automaticamente o `Procfile` e instala as dependências

3. **Configure volume persistente (para o histórico não perder dados)**
   - No painel do Railway, vá em seu serviço → **Volumes** → Add Volume
   - Mount path: `/app/instance`
   - Isso garante que o banco SQLite e os PDFs sobrevivam a re-deploys

4. **Acesse a URL gerada**
   - Railway fornece uma URL pública tipo: `https://r2d-relatorios.up.railway.app`
   - Compartilhe com toda a equipe — não precisa de instalação local

---

## Uso local (desenvolvimento)

```bash
pip install flask reportlab pillow gunicorn
python init_db.py          # cria o banco na primeira vez
python app.py              # sobe em localhost:5050
```

Acesse: http://localhost:5050

---

## Estrutura do projeto

```
r2d-relatorios/
├── app.py              # Flask + geração de PDF (ReportLab)
├── init_db.py          # Inicializa o banco SQLite
├── requirements.txt    # Dependências Python
├── Procfile            # Comando de start para Railway/Heroku
├── railway.json        # Configuração Railway
├── templates/
│   ├── index.html      # Construtor de relatório (prévia ao vivo)
│   └── historico.html  # Histórico de relatórios gerados
└── instance/           # Criada automaticamente
    ├── reports.db      # Banco SQLite
    └── pdfs/           # PDFs gerados
```

---

## Funcionalidades

- **Construtor** com 3 etapas: Dados Gerais → Fotos → Relatório Técnico
- **Prévia ao vivo** simulando todas as páginas do PDF (capa, sumário, fotos, técnico)
- **IA integrada**: analisa legendas das fotos e sugere problemas/soluções técnicas
- **Logos embutidos**: R2D e Banco do Brasil já incluídos em todas as páginas
- **Histórico compartilhado**: todos da equipe veem e baixam relatórios anteriores
- **PDF fiel ao modelo**: capa, informações gerais, sumário, fotos 2/página, relatório técnico

---

## Observações

- O plano gratuito do Railway tem limite de ~500h/mês — suficiente para uso da equipe
- O volume persistente garante que o histórico não seja perdido em re-deploys
- Para trocar os logos, edite as constantes `LOGO_R2D` e `LOGO_BB` em `templates/index.html`

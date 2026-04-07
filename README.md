
# 📥 Webdox Document Downloader

> 💡 Automação inteligente para download em lote de documentos da Webdox via API, com interface gráfica, filtros avançados e geração de relatório.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/Desktop-Tkinter-1F3A5F?style=for-the-badge">
  <img src="https://img.shields.io/badge/API-Webdox-0A66C2?style=for-the-badge">
  <img src="https://img.shields.io/badge/Excel-Report-217346?style=for-the-badge">
  <img src="https://img.shields.io/badge/PDF-Merge-red?style=for-the-badge">
</p>

---
## 📝 Intro

Muitas empresas utilizam CLMs (Contract Lifecycle Management) robustos como a **Webdox**, mas quando surge a necessidade de extrair milhares de contratos para auditorias, due diligence ou backups massivos, a equipe esbarra num gargalo de processos. O tempo gasto com downloads e buscas manuais é insustentável.

Para resolver isso, criei o **Webdox Downloader** — uma automação construída em Python (com interface amigável e pronta para uso) focada em acelerar a estruturação de relatórios e backups.

Se a sua equipe perde dias operando extrações uma a uma, dá uma olhada no que a solução faz de forma 100% automatizada e segura:

⏳ Economia Drástica de Tempo: Transforma semanas de trabalho repetitivo em minutos, lendo IDs de contratos recebidos através de uma planilha CSV.

📂 Organização e Automação: Puxa os documentos e os aloca de forma padronizada em pastas estruturadas.

🔎 Filtro Inteligente Integrado: Você pode definir regras de busca. Ele baixa somente os anexos que possuam termos específicos (ex: "COMPROVANTE") ou extensões (ex: "-assinado.pdf"), ignorando as minutas intermediárias.

📑 Consolidação de Dossies (Merge de PDF): Mais do que só baixar, o sistema une todos os anexos de um mesmo contrato finalizado num único PDF, poupando trabalho na ponta.

📊 Rastreabilidade Máxima: Ao final de cada lote, ele extrai nativamente um log detalhado para o Excel atestando os sucessos, evitando furos do lado da auditoria.



## 🖼️ Preview da Interface

Abaixo estão capturas de tela demonstrando o fluxo de uso da aplicação, desde a autenticação até a conclusão do download.

<p align="center">
  <img src="https://i.ibb.co/GQCnV9sG/webdoxdownloader-1.png" alt="Tela de Login e Configuração Inicial" width="100%">
  <br><em>Figura 1: Tela de Autenticação na API e seleção do arquivo CSV de entrada.</em>
</p>

<p align="center">
  <img src="https://i.ibb.co/ycHNvG0D/webdoxdownloader-2.png" alt="Configuração de Filtros de Busca" width="100%">
  <br><em>Figura 2: Definição dinâmica dos termos de busca e sufixo de arquivo (ex: -assinado.pdf).</em>
</p>

<p align="center">
  <img src="https://i.ibb.co/nNJPm7Ky/webdoxdownloader-3.png" alt="Execução do Download em Tempo Real" width="100%">
  <br><em>Figura 3: Processo de download em lote com log detalhado e barra de progresso.</em>
</p>

<p align="center">
  <img src="https://i.ibb.co/SXNSrkgj/webdoxdownloader-4.png" alt="Estrutura de Arquivos e Relatório Final" width="100%">
  <br><em>Figura 4: Resultado final: pastas organizadas por ID e relatório Excel gerado.</em>
</p>

---

## ✨ Destaques do Projeto

- 🔥 Automação completa de download de documentos
- 📂 Processamento em lote por workflow
- 🔎 Filtro por múltiplos termos de busca
- 🧩 Restrição por sufixo final (ex: `-assinado.pdf`)
- 📥 Download estruturado por workflow
- 🧷 Mesclagem automática de PDFs
- 📊 Relatório final em Excel
- 📡 Integração com API real
- 🧾 Log detalhado em tempo real
- ⏱️ Controle de execução e cancelamento

---

## 🎯 Objetivo

Este projeto foi desenvolvido para resolver um problema comum em operações:

> 📌 **Baixar documentos da Webdox em grande volume, com critério e organização**

Sem automação, esse processo é:

* manual
* repetitivo
* sujeito a erro
* difícil de auditar

💡 A solução transforma isso em um fluxo:

**CSV → API → Filtro → Download → Organização → Relatório**

---

## 🧠 Arquitetura da Solução

```text
            ┌──────────────┐
            │   Usuário    │
            └──────┬───────┘
                   │
                   ▼
        ┌───────────────────┐
        │ Interface Tkinter │
        └────────┬──────────┘
                 │
                 ▼
        ┌───────────────────┐
        │   Motor Python    │
        │   (Orquestração)   │
        └────────┬──────────┘
                 │
     ┌───────────┼────────────┐
     ▼           ▼            ▼
 CSV Reader   API Webdox   Filtros
                 │            │
                 ▼            ▼
            Documentos → Validação
                         │
                         ▼
                  Download Local
                         │
                         ▼
                  Merge de PDFs
                         │
                         ▼
                  Relatório Excel
```

---

## ⚙️ Fluxo da Aplicação

```text
1. Usuário seleciona CSV
2. Sistema autentica na API
3. Loop por workflow_id:
    ├─ Consulta documentos
    ├─ Aplica filtros (termos + sufixo)
    ├─ Baixa arquivos válidos
    └─ Organiza por pasta
4. (Opcional) Mescla PDFs
5. Gera relatório final
```

---

## 🔎 Lógica de Busca

### Um documento será baixado se:

✔ Contiver pelo menos **um termo de busca**
✔ E (opcionalmente) terminar com o **sufixo definido**

---

### 💡 Exemplo

**Termos:**

```text
NF
COMPROVANTE
```

**Sufixo:**

```text
-assinado.pdf
```

📥 Resultado:

* arquivos com `NF` OU `COMPROVANTE`
* E que terminem com `-assinado.pdf`

---

## 🧩 Funcionalidades

### 🔐 Autenticação

* login direto via API Webdox
* suporte a refresh de token

### 📂 Entrada via CSV

```csv
workflow_id
12345
67890
```

### 🔎 Termos dinâmicos

* adicionar/remover via interface
* múltiplos termos simultâneos

### 🧷 Sufixo final

* filtro global
* restringe resultados finais

### 📥 Download automatizado

* organização por workflow

### 🧷 Merge de PDFs

* 1 PDF consolidado por workflow

### 📊 Relatório Excel

* controle completo da execução

---

## 📦 Estrutura de saída

```text
downloads_webdox/
├── workflow_12345/
│   ├── doc1.pdf
│   ├── doc2.pdf
│   └── workflow_12345__MERGED.pdf
├── workflow_67890/
└── RELATORIO_DOWNLOADS.xlsx
```

---

## 📊 Relatório gerado

| Campo            | Descrição        |
| ---------------- | ---------------- |
| workflow_id      | ID do workflow   |
| workflow_name    | Nome             |
| docs_encontrados | Total localizado |
| docs_baixados    | Total baixado    |

---

## 🛠️ Tecnologias

* Python 3
* Tkinter
* Requests
* OpenPyXL
* PyPDF

---

## 📋 Pré-requisitos

* Python 3.9+
* Conta Webdox
* CSV com workflow_id

---

## 🔧 Instalação

```bash
git clone https://github.com/Pinheiro-dataset/Webdox-Downloader.git
cd webdox-document-downloader

- Gerar o executável com PyInstaller

py -m pip install --upgrade pip
py -m pip install requests openpyxl pypdf
py -m pip install requests pypdf pyinstaller
py -m PyInstaller --clean --noconfirm --onefile --noconsole --name WebdoxDownloader webdox_downloader.py
```

---

## ▶️ Execução

```bash
WebdoxDownloader.exe
```

---

## 🌐 API padrão

```text
https://api.webdoxclm.com/api/v2
```

---

## 🚀 O Problema que este App Resolve
Para equipes jurídicas, de Legal Ops e Tecnologia, gerenciar grandes volumes de contratos em sistemas CLM (Contract Lifecycle Management) como o Webdox pode ser um desafio metodológico. Quando surge a necessidade de extrair milhares de contratos para auditorias, due diligence, migrações de sistema ou apenas para a guarda de backup secundário, a extração manual se torna uma tarefa insustentável, custando semanas de trabalho operacional.

O **Webdox Downloader** foi concebido exatamente para sanar essa dor. Trata-se de uma solução corporativa que automatiza a extração e a organização de documentos a partir da API oficial v2 da Webdox, devolvendo o tempo da equipe para atividades estratégicas.

---

### 💡 Principais Benefícios e Recursos
* **🕐 Economia Drástica de Tempo (Horas -> Minutos):** Elimine o trabalho braçal e repetitivo. Faça na hora o que levaria semanas para ser feito com cliques manuais.
* **📂 Organização Automática e Parametrizada:** Os arquivos são extraídos estruturados por ID do Workflow (via integração com CSV), acabando com as pastas bagunçadas.
* **🔎 Busca Dinâmica e Filtros Inteligentes:** Baixe apenas o que interessa. Filtre documentos específicos pelo nome (ex: "COMPROVANTE") e fixe extensões customizadas ("-assinado.pdf").
* **📄 Consolidação de PDFs:** Função inteligente que mescla múltiplos anexos baixados em um fluxo único de PDF, mantendo os dossiês e fluxogramas documentais intactos.
* **🛡️ Conformidade e Relatórios:** Rastreabilidade máxima. A ferramenta extrai um Excel nativo detalhando os sucessos, falhas e o total de arquivos baixados por operation, ideal para evidenciar segurança em auditorias.
* **⚡ Interface Rica e Resiliente:** Processamento concorrente (Threads) para não travar a aplicação, tratamento nativo de limites de API (Rate Limit 429) e logs robustos para o usuário final, eliminando a barreira técnica para áreas operacionais.

---

## 📈 Evoluções futuras

* filtros por data
* exportação de logs
* histórico de execuções
* configuração via `.env`
* versão executável (.exe)
* paginação API
* dashboard de execução

---

## 👨‍💻 Autor

**Rodrigo Pinheiro**
🔗 [https://www.linkedin.com/in/rodrigo-s-pinheiro/](https://www.linkedin.com/in/rodrigo-s-pinheiro/)

---

## 📄 Licença

MIT

---

## 🎉 Conclusão

Este projeto transforma uma dor operacional real em uma solução:

👉 Automatizada
👉 Escalável
👉 Reutilizável
👉 Apresentável como produto

Mais do que um script, é um **case de engenharia aplicada a negócio**.

🚀
# SQL RAG Optimizer

Ferramenta para converter dumps de banco de dados SQL Anywhere para formato otimizado para uso em RAG (Retrieval-Augmented Generation).

## Problema

Arquivos de dump gerados pelo `dbunload` do SQL Anywhere contêm muita informação irrelevante para RAG:
- Configurações de usuários e permissões
- Roles e grants
- Spatial reference systems
- etc.

Além disso, o formato padrão pode fragmentar definições de tabelas em múltiplos chunks, prejudicando a recuperação de contexto.

## Solução

Este script extrai apenas a estrutura relevante das tabelas e formata de forma compacta:
- Nome da tabela e descrição
- Colunas com tipos, constraints e comentários
- Chaves primárias

## Instalação

```bash
# Clone o repositório
git clone https://github.com/TiagoRossoTR/sql-rag-optimizer.git
cd sql-rag-optimizer

# Não há dependências externas além do Python 3.7+
```

## Uso

```bash
python convert_dump_to_rag.py entrada.txt saida_rag.txt
```

### Opções

- `--schema SCHEMA` - Filtrar por schema específico (ex: `bethadba`)
- `--encoding ENCODING` - Encoding do arquivo de entrada (padrão: `latin-1`)

### Exemplo

```bash
# Converter dump completo
python convert_dump_to_rag.py Estrutura_banco_contabil.txt estrutura_rag.txt

# Converter apenas tabelas do schema bethadba
python convert_dump_to_rag.py Estrutura_banco_contabil.txt estrutura_rag.txt --schema bethadba
```

## Formato de Saída

```
================================================================================
TABELA: bethadba.ctbaklan
DESCRIÇÃO: Lancamentos Eliminados
--------------------------------------------------------------------------------
COLUNAS:
- codi_emp (integer NOT NULL) [PK] - Código da empresa
- nume_lan (integer NOT NULL) [PK] - Número do lançamento
- data_lan (date NOT NULL) - Data do lançamento
- vlor_lan (numeric(14,2) NOT NULL) - Valor do lançamento
...

CHAVE PRIMÁRIA: (codi_emp, nume_lan)
================================================================================
```

## Benefícios para RAG

1. **Chunks menores**: Cada tabela cabe em ~1-2KB
2. **Informação densa**: Apenas dados relevantes
3. **Separadores claros**: Facilita chunking inteligente
4. **Contexto completo**: Toda informação da tabela em um bloco

## Configurações recomendadas para Open Arena

Após gerar o arquivo otimizado:

| Parâmetro | Valor Recomendado |
|-----------|-------------------|
| Chunk Size | 4096 |
| Chunk Overlap | 15-20% |
| Size (top_k) | 25-30 |
| Temperature | 0.2 |

## Licença

MIT

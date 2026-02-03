#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQL RAG Optimizer - Interface Interativa

Converte dump do SQL Anywhere (dbunload) para formato otimizado para RAG.
Interface visual no terminal com menus e barra de progresso.

Autor: TiagoRossoTR
"""

import re
import sys
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich import print as rprint
    from rich.markdown import Markdown
except ImportError:
    print("Instalando dependência 'rich'...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich"])
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich import print as rprint
    from rich.markdown import Markdown

console = Console()


# ============================================================================
# MODELOS DE DADOS
# ============================================================================

@dataclass
class Column:
    """Representa uma coluna de tabela."""
    name: str
    data_type: str
    nullable: bool = True
    default: str = ""
    comment: str = ""
    is_pk: bool = False


@dataclass
class Table:
    """Representa uma tabela do banco de dados."""
    schema: str
    name: str
    columns: List[Column] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    comment: str = ""
    
    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"


# ============================================================================
# PARSER
# ============================================================================

class DumpParser:
    """Parser para arquivos de dump do SQL Anywhere."""
    
    def __init__(self, console: Console):
        self.tables: Dict[str, Table] = {}
        self.current_content = ""
        self.console = console
        
    def parse_file(self, filepath: str) -> Dict[str, Table]:
        """Lê e parseia o arquivo de dump."""
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self.console
        ) as progress:
            
            # Ler arquivo
            task1 = progress.add_task("[cyan]Lendo arquivo...", total=100)
            
            with open(filepath, 'r', encoding='latin-1') as f:
                self.current_content = f.read()
            
            progress.update(task1, completed=100)
            
            # Extrair CREATE TABLEs
            task2 = progress.add_task("[cyan]Extraindo tabelas...", total=100)
            self._parse_create_tables()
            progress.update(task2, completed=100)
            
            # Extrair COMMENTs
            task3 = progress.add_task("[cyan]Extraindo comentários...", total=100)
            self._parse_comments()
            progress.update(task3, completed=100)
        
        return self.tables
    
    def _parse_create_tables(self):
        """Extrai definições de CREATE TABLE."""
        pattern = r'CREATE\s+TABLE\s+"([^"]+)"\."([^"]+)"\s*\((.*?)\)\s*(?:go|;)'
        
        matches = re.findall(pattern, self.current_content, re.DOTALL | re.IGNORECASE)
        
        for schema, table_name, columns_def in matches:
            table = Table(schema=schema, name=table_name)
            self._parse_columns(table, columns_def)
            self.tables[table.full_name.lower()] = table
    
    def _parse_columns(self, table: Table, columns_def: str):
        """Extrai definições de colunas."""
        lines = self._split_columns(columns_def)
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Ignorar constraints, mas extrair PRIMARY KEY
            if re.match(r'^\s*(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|CONSTRAINT)', line, re.IGNORECASE):
                pk_match = re.search(r'PRIMARY\s+KEY\s*\(([^)]+)\)', line, re.IGNORECASE)
                if pk_match:
                    pk_cols = [c.strip().strip('"') for c in pk_match.group(1).split(',')]
                    table.primary_key = pk_cols
                    for col in table.columns:
                        if col.name in pk_cols:
                            col.is_pk = True
                continue
            
            # Parsear coluna
            col_match = re.match(
                r'"([^"]+)"\s+(\w+(?:\([^)]+\))?)\s*(NOT\s+NULL|NULL)?\s*(DEFAULT\s+.+)?',
                line,
                re.IGNORECASE
            )
            
            if col_match:
                col_name = col_match.group(1)
                col_type = col_match.group(2)
                nullable = col_match.group(3)
                default = col_match.group(4) or ""
                
                is_nullable = True
                if nullable and 'NOT NULL' in nullable.upper():
                    is_nullable = False
                
                column = Column(
                    name=col_name,
                    data_type=col_type,
                    nullable=is_nullable,
                    default=default.replace('DEFAULT ', '').strip() if default else ""
                )
                table.columns.append(column)
    
    def _split_columns(self, columns_def: str) -> List[str]:
        """Divide definição de colunas respeitando parênteses."""
        result = []
        current = ""
        depth = 0
        
        for char in columns_def:
            if char == '(':
                depth += 1
                current += char
            elif char == ')':
                depth -= 1
                current += char
            elif char == ',' and depth == 0:
                result.append(current)
                current = ""
            else:
                current += char
        
        if current.strip():
            result.append(current)
        
        return result
    
    def _parse_comments(self):
        """Extrai COMMENT ON TABLE e COMMENT ON COLUMN."""
        
        # COMMENT ON TABLE
        table_pattern = r'COMMENT\s+ON\s+TABLE\s+"([^"]+)"\."([^"]+)"\s+IS\s+\'([^\']*)\''
        for match in re.finditer(table_pattern, self.current_content, re.IGNORECASE):
            schema, table_name, comment = match.groups()
            full_name = f"{schema}.{table_name}".lower()
            if full_name in self.tables:
                self.tables[full_name].comment = comment
        
        # COMMENT ON COLUMN
        col_pattern = r'COMMENT\s+ON\s+COLUMN\s+"([^"]+)"\."([^"]+)"\."([^"]+)"\s+IS\s+\'([^\']*)\''
        for match in re.finditer(col_pattern, self.current_content, re.IGNORECASE):
            schema, table_name, col_name, comment = match.groups()
            full_name = f"{schema}.{table_name}".lower()
            if full_name in self.tables:
                for col in self.tables[full_name].columns:
                    if col.name.lower() == col_name.lower():
                        col.comment = comment
                        break


# ============================================================================
# FORMATADOR
# ============================================================================

class RagFormatter:
    """Formata tabelas para output otimizado para RAG."""
    
    SEPARATOR = "=" * 80
    SUBSEPARATOR = "-" * 80
    
    def format_tables(self, tables: Dict[str, Table]) -> str:
        """Formata todas as tabelas para output RAG."""
        output_parts = []
        sorted_tables = sorted(tables.values(), key=lambda t: t.full_name)
        
        for table in sorted_tables:
            output_parts.append(self._format_table(table))
        
        return "\n".join(output_parts)
    
    def _format_table(self, table: Table) -> str:
        """Formata uma única tabela."""
        lines = [
            self.SEPARATOR,
            f"TABELA: {table.full_name}",
        ]
        
        if table.comment:
            lines.append(f"DESCRIÇÃO: {table.comment}")
        
        lines.append(self.SUBSEPARATOR)
        lines.append("COLUNAS:")
        
        for col in table.columns:
            col_line = self._format_column(col)
            lines.append(col_line)
        
        if table.primary_key:
            lines.append("")
            lines.append(f"CHAVE PRIMÁRIA: ({', '.join(table.primary_key)})")
        
        lines.append(self.SEPARATOR)
        lines.append("")
        
        return "\n".join(lines)
    
    def _format_column(self, col: Column) -> str:
        """Formata uma coluna."""
        parts = [f"- {col.name}"]
        
        nullable_str = "NULL" if col.nullable else "NOT NULL"
        parts.append(f"({col.data_type} {nullable_str})")
        
        indicators = []
        if col.is_pk:
            indicators.append("PK")
        
        if indicators:
            parts.append(f"[{', '.join(indicators)}]")
        
        if col.comment:
            parts.append(f"- {col.comment}")
        
        return " ".join(parts)


# ============================================================================
# INTERFACE
# ============================================================================

def show_banner():
    """Exibe banner do aplicativo."""
    banner = """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   ███████╗ ██████╗ ██╗         ██████╗  █████╗  ██████╗                        ║
║   ██╔════╝██╔═══██╗██║         ██╔══██╗██╔══██╗██╔════╝                        ║
║   ███████╗██║   ██║██║         ██████╔╝███████║██║  ███╗                       ║
║   ╚════██║██║▄▄ ██║██║         ██╔══██╗██╔══██║██║   ██║                       ║
║   ███████║╚██████╔╝███████╗    ██║  ██║██║  ██║╚██████╔╝                       ║
║   ╚══════╝ ╚══▀▀═╝ ╚══════╝    ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝                        ║
║                                                                               ║
║                    O P T I M I Z E R                                          ║
║                                                                               ║
║   Converte dumps SQL Anywhere para formato otimizado para RAG                 ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
    console.print(banner, style="bold cyan")


def show_menu() -> str:
    """Exibe menu principal e retorna opção selecionada."""
    console.print()
    console.print("[bold yellow]═══ MENU PRINCIPAL ═══[/bold yellow]")
    console.print()
    console.print("  [bold green]1.[/bold green] Converter arquivo de dump")
    console.print("  [bold green]2.[/bold green] Ver estatísticas de arquivo")
    console.print("  [bold green]3.[/bold green] Configurações recomendadas para RAG")
    console.print("  [bold green]4.[/bold green] Ajuda")
    console.print("  [bold red]0.[/bold red] Sair")
    console.print()
    
    choice = Prompt.ask("[bold cyan]Escolha uma opção[/bold cyan]", choices=["0", "1", "2", "3", "4"], default="1")
    return choice


def get_input_file() -> Optional[str]:
    """Solicita arquivo de entrada."""
    console.print()
    console.print("[bold yellow]═══ SELECIONAR ARQUIVO ═══[/bold yellow]")
    console.print()
    
    # Listar arquivos .txt na pasta atual
    current_files = [f for f in os.listdir('.') if f.endswith(('.txt', '.sql')) and os.path.isfile(f)]
    
    if current_files:
        console.print("[dim]Arquivos encontrados na pasta atual:[/dim]")
        for i, f in enumerate(current_files, 1):
            size = os.path.getsize(f) / (1024 * 1024)  # MB
            console.print(f"  [green]{i}.[/green] {f} [dim]({size:.2f} MB)[/dim]")
        console.print()
    
    filepath = Prompt.ask(
        "[bold cyan]Digite o caminho do arquivo (ou número da lista)[/bold cyan]",
        default=current_files[0] if len(current_files) == 1 else ""
    )
    
    # Se digitou número, pegar da lista
    if filepath.isdigit() and current_files:
        idx = int(filepath) - 1
        if 0 <= idx < len(current_files):
            filepath = current_files[idx]
    
    if not os.path.exists(filepath):
        console.print(f"[bold red]✗ Arquivo não encontrado: {filepath}[/bold red]")
        return None
    
    return filepath


def get_output_file(input_file: str) -> str:
    """Solicita arquivo de saída."""
    default_output = Path(input_file).stem + "_rag.txt"
    
    output = Prompt.ask(
        "[bold cyan]Arquivo de saída[/bold cyan]",
        default=default_output
    )
    
    return output


def convert_file():
    """Executa conversão de arquivo."""
    input_file = get_input_file()
    if not input_file:
        return
    
    output_file = get_output_file(input_file)
    
    # Filtro de schema
    filter_schema = Prompt.ask(
        "[bold cyan]Filtrar por schema? (deixe vazio para todos)[/bold cyan]",
        default=""
    )
    
    console.print()
    console.print("[bold yellow]═══ PROCESSANDO ═══[/bold yellow]")
    console.print()
    
    # Parsear
    parser = DumpParser(console)
    tables = parser.parse_file(input_file)
    
    # Filtrar
    if filter_schema:
        tables = {k: v for k, v in tables.items() if v.schema.lower() == filter_schema.lower()}
    
    # Formatar
    formatter = RagFormatter()
    output = formatter.format_tables(tables)
    
    # Salvar
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output)
    
    # Estatísticas
    console.print()
    show_result_stats(input_file, output_file, tables, output)


def show_result_stats(input_file: str, output_file: str, tables: dict, output: str):
    """Exibe estatísticas do resultado."""
    input_size = os.path.getsize(input_file) / (1024 * 1024)
    output_size = len(output.encode('utf-8')) / (1024 * 1024)
    reduction = (1 - output_size / input_size) * 100 if input_size > 0 else 0
    
    stats_table = Table.grid(padding=1)
    stats_table.add_column(style="cyan", justify="right")
    stats_table.add_column(style="white")
    
    stats_table.add_row("📄 Arquivo de entrada:", input_file)
    stats_table.add_row("📄 Arquivo de saída:", output_file)
    stats_table.add_row("📊 Tamanho entrada:", f"{input_size:.2f} MB")
    stats_table.add_row("📊 Tamanho saída:", f"{output_size:.2f} MB")
    stats_table.add_row("📉 Redução:", f"{reduction:.1f}%")
    stats_table.add_row("📋 Tabelas extraídas:", str(len(tables)))
    
    total_cols = sum(len(t.columns) for t in tables.values())
    stats_table.add_row("📋 Colunas totais:", str(total_cols))
    
    panel = Panel(
        stats_table,
        title="[bold green]✓ Conversão Concluída[/bold green]",
        border_style="green"
    )
    console.print(panel)


def show_file_stats():
    """Mostra estatísticas de um arquivo sem converter."""
    input_file = get_input_file()
    if not input_file:
        return
    
    console.print()
    console.print("[bold yellow]═══ ANALISANDO ═══[/bold yellow]")
    console.print()
    
    parser = DumpParser(console)
    tables = parser.parse_file(input_file)
    
    # Estatísticas por schema
    schemas = {}
    for table in tables.values():
        if table.schema not in schemas:
            schemas[table.schema] = 0
        schemas[table.schema] += 1
    
    console.print()
    stats_table = Table(title="Estatísticas do Arquivo")
    stats_table.add_column("Schema", style="cyan")
    stats_table.add_column("Tabelas", justify="right", style="green")
    
    for schema, count in sorted(schemas.items()):
        stats_table.add_row(schema, str(count))
    
    stats_table.add_row("[bold]TOTAL[/bold]", f"[bold]{len(tables)}[/bold]")
    
    console.print(stats_table)


def show_rag_config():
    """Mostra configurações recomendadas para RAG."""
    console.print()
    
    config_text = """
## Configurações Recomendadas para Open Arena

Após gerar o arquivo otimizado, configure sua chain com:

### RAG Settings
| Parâmetro | Valor |
|-----------|-------|
| Chunk Size | **4096** (máximo) |
| Chunk Overlap | **15-20%** |
| Size (top_k) | **25-30** |

### Model Settings
| Parâmetro | Valor |
|-----------|-------|
| Temperature | **0.2** |
| Enable Reasoning | **On** |

### Benefícios
- Cada tabela cabe em 1-2 chunks
- Contexto completo preservado
- Respostas mais consistentes
"""
    
    md = Markdown(config_text)
    panel = Panel(md, title="[bold cyan]Configurações RAG[/bold cyan]", border_style="cyan")
    console.print(panel)


def show_help():
    """Mostra ajuda."""
    console.print()
    
    help_text = """
## SQL RAG Optimizer - Ajuda

### O que faz?
Converte arquivos de dump do SQL Anywhere (gerados pelo `dbunload`) 
para um formato compacto e otimizado para uso em RAG.

### Por que usar?
- Remove informações irrelevantes (usuários, roles, grants)
- Formata tabelas de forma compacta (~1KB por tabela)
- Adiciona separadores claros para facilitar chunking
- Preserva descrições de tabelas e colunas

### Formato de saída
```
================================================================================
TABELA: schema.nome_tabela
DESCRIÇÃO: Descrição da tabela
--------------------------------------------------------------------------------
COLUNAS:
- coluna (tipo NULL/NOT NULL) [PK] - Descrição

CHAVE PRIMÁRIA: (col1, col2)
================================================================================
```

### Uso via linha de comando
```
python convert_dump_to_rag.py entrada.txt saida.txt --schema bethadba
```
"""
    
    md = Markdown(help_text)
    panel = Panel(md, title="[bold cyan]Ajuda[/bold cyan]", border_style="cyan")
    console.print(panel)


def main():
    """Função principal."""
    show_banner()
    
    while True:
        choice = show_menu()
        
        if choice == "0":
            console.print()
            console.print("[bold cyan]Até logo! 👋[/bold cyan]")
            break
        elif choice == "1":
            convert_file()
        elif choice == "2":
            show_file_stats()
        elif choice == "3":
            show_rag_config()
        elif choice == "4":
            show_help()
        
        console.print()
        input("Pressione ENTER para continuar...")


if __name__ == '__main__':
    main()

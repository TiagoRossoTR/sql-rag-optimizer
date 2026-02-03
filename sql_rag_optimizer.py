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
    from rich.table import Table as RichTable
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
    from rich.table import Table as RichTable
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
class ForeignKey:
    """Representa uma foreign key."""
    name: str
    table_schema: str
    table_name: str
    columns: List[str]
    ref_schema: str
    ref_table: str
    ref_columns: List[str]
    
    @property
    def full_table_name(self) -> str:
        return f"{self.table_schema}.{self.table_name}"


@dataclass
class Index:
    """Representa um índice."""
    name: str
    table_schema: str
    table_name: str
    columns: List[str]
    is_unique: bool = False
    
    @property
    def full_table_name(self) -> str:
        return f"{self.table_schema}.{self.table_name}"


@dataclass
class Function:
    """Representa uma função."""
    schema: str
    name: str
    parameters: str
    return_type: str
    
    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass
class Procedure:
    """Representa uma procedure."""
    schema: str
    name: str
    parameters: str
    
    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass
class DatabaseTable:
    """Representa uma tabela do banco de dados."""
    schema: str
    name: str
    columns: List[Column] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)
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
        self.tables: Dict[str, DatabaseTable] = {}
        self.functions: Dict[str, Function] = {}
        self.procedures: Dict[str, Procedure] = {}
        self.current_content = ""
        self.console = console
        
    def parse_file(self, filepath: str) -> Dict[str, DatabaseTable]:
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
            
            with open(filepath, 'r', encoding='windows-1252') as f:
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
            
            # Extrair Foreign Keys
            task4 = progress.add_task("[cyan]Extraindo foreign keys...", total=100)
            self._parse_foreign_keys()
            progress.update(task4, completed=100)
            
            # Extrair Índices
            task5 = progress.add_task("[cyan]Extraindo índices...", total=100)
            self._parse_indexes()
            progress.update(task5, completed=100)
            
            # Extrair Funções
            task6 = progress.add_task("[cyan]Extraindo funções...", total=100)
            self._parse_functions()
            progress.update(task6, completed=100)
            
            # Extrair Procedures
            task7 = progress.add_task("[cyan]Extraindo procedures...", total=100)
            self._parse_procedures()
            progress.update(task7, completed=100)
        
        return self.tables
    
    def _parse_create_tables(self):
        """Extrai definições de CREATE TABLE."""
        pattern = r'CREATE\s+TABLE\s+"([^"]+)"\."([^"]+)"\s*\((.*?)\)\s*(?:go|;)'
        
        matches = re.findall(pattern, self.current_content, re.DOTALL | re.IGNORECASE)
        
        for schema, table_name, columns_def in matches:
            table = DatabaseTable(schema=schema, name=table_name)
            self._parse_columns(table, columns_def)
            self.tables[table.full_name.lower()] = table
    
    def _parse_columns(self, table: DatabaseTable, columns_def: str):
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
    
    def _parse_foreign_keys(self):
        """Extrai FOREIGN KEYs."""
        # ALTER TABLE "schema"."table" ADD FOREIGN KEY "name" (cols) REFERENCES "schema"."table" (cols)
        pattern = r'ALTER\s+TABLE\s+"([^"]+)"\."([^"]+)"\s+ADD\s+FOREIGN\s+KEY\s+"([^"]+)"\s*\(([^)]+)\)\s*REFERENCES\s+"([^"]+)"\."([^"]+)"\s*\(([^)]+)\)'
        
        for match in re.finditer(pattern, self.current_content, re.IGNORECASE):
            schema, table_name, fk_name, columns, ref_schema, ref_table, ref_columns = match.groups()
            
            # Limpar nomes de colunas
            cols = [c.strip().strip('"').replace(' ASC', '').replace(' DESC', '') for c in columns.split(',')]
            ref_cols = [c.strip().strip('"').replace(' ASC', '').replace(' DESC', '') for c in ref_columns.split(',')]
            
            fk = ForeignKey(
                name=fk_name,
                table_schema=schema,
                table_name=table_name,
                columns=cols,
                ref_schema=ref_schema,
                ref_table=ref_table,
                ref_columns=ref_cols
            )
            
            # Adicionar à tabela correspondente
            full_name = f"{schema}.{table_name}".lower()
            if full_name in self.tables:
                self.tables[full_name].foreign_keys.append(fk)
    
    def _parse_indexes(self):
        """Extrai índices."""
        # CREATE [UNIQUE] INDEX "name" ON "schema"."table" (cols)
        pattern = r'CREATE\s+(UNIQUE\s+)?INDEX\s+"([^"]+)"\s+ON\s+"([^"]+)"\."([^"]+)"\s*\(([^)]+)\)'
        
        for match in re.finditer(pattern, self.current_content, re.IGNORECASE):
            unique, idx_name, schema, table_name, columns = match.groups()
            
            # Limpar nomes de colunas
            cols = [c.strip().strip('"').replace(' ASC', '').replace(' DESC', '') for c in columns.split(',')]
            
            idx = Index(
                name=idx_name,
                table_schema=schema,
                table_name=table_name,
                columns=cols,
                is_unique=bool(unique)
            )
            
            # Adicionar à tabela correspondente
            full_name = f"{schema}.{table_name}".lower()
            if full_name in self.tables:
                self.tables[full_name].indexes.append(idx)
    
    def _parse_functions(self):
        """Extrai funções."""
        # create function "schema"."name"(params) returns type
        pattern = r'create\s+function\s+"([^"]+)"\."([^"]+)"\s*\(([^)]*)\)\s*returns\s+(\w+)'
        
        for match in re.finditer(pattern, self.current_content, re.IGNORECASE):
            schema, func_name, params, return_type = match.groups()
            
            # Simplificar parâmetros
            params_clean = self._simplify_params(params)
            
            func = Function(
                schema=schema,
                name=func_name,
                parameters=params_clean,
                return_type=return_type
            )
            
            self.functions[func.full_name.lower()] = func
    
    def _parse_procedures(self):
        """Extrai procedures."""
        # create procedure "schema"."name"(params)
        pattern = r'create\s+procedure\s+"([^"]+)"\."([^"]+)"\s*\(([^)]*)\)'
        
        for match in re.finditer(pattern, self.current_content, re.IGNORECASE):
            schema, proc_name, params = match.groups()
            
            # Simplificar parâmetros
            params_clean = self._simplify_params(params)
            
            proc = Procedure(
                schema=schema,
                name=proc_name,
                parameters=params_clean
            )
            
            self.procedures[proc.full_name.lower()] = proc
    
    def _simplify_params(self, params: str) -> str:
        """Simplifica lista de parâmetros."""
        if not params.strip():
            return ""
        
        result = []
        # Quebrar por vírgula (cuidando com defaults)
        parts = params.split(',')
        for part in parts:
            part = part.strip()
            # Extrair: in/out "nome" tipo
            match = re.match(r'(in|out|inout)?\s*"?(\w+)"?\s+(\w+)', part, re.IGNORECASE)
            if match:
                direction, name, ptype = match.groups()
                direction = direction or "in"
                result.append(f"{direction} {name} {ptype}")
        
        return ", ".join(result)


# ============================================================================
# FORMATADOR
# ============================================================================

class RagFormatter:
    """Formata tabelas para output otimizado para RAG."""
    
    SEPARATOR = "=" * 80
    SUBSEPARATOR = "-" * 80
    
    def format_all(self, tables: Dict[str, DatabaseTable], 
                   functions: Dict[str, Function], 
                   procedures: Dict[str, Procedure]) -> str:
        """Formata tudo para output RAG."""
        output_parts = []
        
        # Tabelas
        sorted_tables = sorted(tables.values(), key=lambda t: t.full_name)
        for table in sorted_tables:
            output_parts.append(self._format_table(table))
        
        # Funções
        if functions:
            output_parts.append(self._format_functions_section(functions))
        
        # Procedures
        if procedures:
            output_parts.append(self._format_procedures_section(procedures))
        
        return "\n".join(output_parts)
    
    def format_tables(self, tables: Dict[str, DatabaseTable]) -> str:
        """Formata todas as tabelas para output RAG (compatibilidade)."""
        output_parts = []
        sorted_tables = sorted(tables.values(), key=lambda t: t.full_name)
        
        for table in sorted_tables:
            output_parts.append(self._format_table(table))
        
        return "\n".join(output_parts)
    
    def _format_table(self, table: DatabaseTable) -> str:
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
        
        # Foreign Keys
        if table.foreign_keys:
            lines.append("")
            lines.append("FOREIGN KEYS:")
            for fk in table.foreign_keys:
                fk_line = f"- {fk.name}: ({', '.join(fk.columns)}) -> {fk.ref_schema}.{fk.ref_table}({', '.join(fk.ref_columns)})"
                lines.append(fk_line)
        
        # Índices
        if table.indexes:
            lines.append("")
            lines.append("ÍNDICES:")
            for idx in table.indexes:
                unique_str = "UNIQUE " if idx.is_unique else ""
                idx_line = f"- {idx.name}: {unique_str}({', '.join(idx.columns)})"
                lines.append(idx_line)
        
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
    
    def _format_functions_section(self, functions: Dict[str, Function]) -> str:
        """Formata seção de funções."""
        lines = [
            self.SEPARATOR,
            "FUNÇÕES DO BANCO DE DADOS",
            self.SUBSEPARATOR,
        ]
        
        for func in sorted(functions.values(), key=lambda f: f.full_name):
            lines.append(f"- {func.full_name}({func.parameters}) -> {func.return_type}")
        
        lines.append(self.SEPARATOR)
        lines.append("")
        
        return "\n".join(lines)
    
    def _format_procedures_section(self, procedures: Dict[str, Procedure]) -> str:
        """Formata seção de procedures."""
        lines = [
            self.SEPARATOR,
            "PROCEDURES DO BANCO DE DADOS",
            self.SUBSEPARATOR,
        ]
        
        for proc in sorted(procedures.values(), key=lambda p: p.full_name):
            lines.append(f"- {proc.full_name}({proc.parameters})")
        
        lines.append(self.SEPARATOR)
        lines.append("")
        
        return "\n".join(lines)


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
    console.print("  [bold green]1.[/bold green] Converter arquivo (único)")
    console.print("  [bold green]2.[/bold green] Converter arquivo (múltiplos por tipo)")
    console.print("  [bold green]3.[/bold green] Converter arquivo (múltiplos por módulo)")
    console.print("  [bold green]4.[/bold green] Ver estatísticas de arquivo")
    console.print("  [bold green]5.[/bold green] Configurações recomendadas para RAG")
    console.print("  [bold green]6.[/bold green] Ajuda")
    console.print("  [bold red]0.[/bold red] Sair")
    console.print()
    
    choice = Prompt.ask("[bold cyan]Escolha uma opção[/bold cyan]", choices=["0", "1", "2", "3", "4", "5", "6"], default="1")
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
    functions = parser.functions
    procedures = parser.procedures
    
    # Filtrar por schema
    if filter_schema:
        tables = {k: v for k, v in tables.items() if v.schema.lower() == filter_schema.lower()}
        functions = {k: v for k, v in functions.items() if v.schema.lower() == filter_schema.lower()}
        procedures = {k: v for k, v in procedures.items() if v.schema.lower() == filter_schema.lower()}
    
    # Formatar
    formatter = RagFormatter()
    output = formatter.format_all(tables, functions, procedures)
    
    # Salvar em UTF-8 (recomendado para RAG/Open Arena)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output)
    
    # Estatísticas
    console.print()
    show_result_stats(input_file, output_file, tables, functions, procedures, output)


def show_result_stats(input_file: str, output_file: str, tables: dict, functions: dict, procedures: dict, output: str):
    """Exibe estatísticas do resultado."""
    input_size = os.path.getsize(input_file) / (1024 * 1024)
    output_size = len(output.encode('utf-8')) / (1024 * 1024)
    reduction = (1 - output_size / input_size) * 100 if input_size > 0 else 0
    
    stats_table = RichTable.grid(padding=1)
    stats_table.add_column(style="cyan", justify="right")
    stats_table.add_column(style="white")
    
    stats_table.add_row("📄 Arquivo de entrada:", input_file)
    stats_table.add_row("📄 Arquivo de saída:", output_file)
    stats_table.add_row("📊 Tamanho entrada:", f"{input_size:.2f} MB")
    stats_table.add_row("📊 Tamanho saída:", f"{output_size:.2f} MB")
    stats_table.add_row("📉 Redução:", f"{reduction:.1f}%")
    stats_table.add_row("", "")
    stats_table.add_row("📋 Tabelas:", str(len(tables)))
    
    total_cols = sum(len(t.columns) for t in tables.values())
    stats_table.add_row("📋 Colunas:", str(total_cols))
    
    total_fks = sum(len(t.foreign_keys) for t in tables.values())
    stats_table.add_row("🔗 Foreign Keys:", str(total_fks))
    
    total_idx = sum(len(t.indexes) for t in tables.values())
    stats_table.add_row("📇 Índices:", str(total_idx))
    
    stats_table.add_row("⚡ Funções:", str(len(functions)))
    stats_table.add_row("📦 Procedures:", str(len(procedures)))
    
    panel = Panel(
        stats_table,
        title="[bold green]✓ Conversão Concluída[/bold green]",
        border_style="green"
    )
    console.print(panel)


def convert_file_by_type():
    """Converte arquivo gerando múltiplos arquivos por tipo."""
    input_file = get_input_file()
    if not input_file:
        return
    
    # Pasta de saída
    output_dir = Prompt.ask(
        "[bold cyan]Pasta de saída[/bold cyan]",
        default="output_por_tipo"
    )
    
    os.makedirs(output_dir, exist_ok=True)
    
    console.print()
    console.print("[bold yellow]═══ PROCESSANDO ═══[/bold yellow]")
    console.print()
    
    # Parsear
    parser = DumpParser(console)
    tables = parser.parse_file(input_file)
    functions = parser.functions
    procedures = parser.procedures
    
    formatter = RagFormatter()
    files_created = []
    
    # Arquivo de tabelas
    if tables:
        output = formatter.format_tables(tables)
        filepath = os.path.join(output_dir, "tabelas.txt")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(output)
        files_created.append(("tabelas.txt", len(tables), len(output)))
    
    # Arquivo de funções
    if functions:
        output = formatter._format_functions_section(functions)
        filepath = os.path.join(output_dir, "funcoes.txt")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(output)
        files_created.append(("funcoes.txt", len(functions), len(output)))
    
    # Arquivo de procedures
    if procedures:
        output = formatter._format_procedures_section(procedures)
        filepath = os.path.join(output_dir, "procedures.txt")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(output)
        files_created.append(("procedures.txt", len(procedures), len(output)))
    
    # Mostrar resultado
    console.print()
    result_table = RichTable(title="Arquivos Gerados por Tipo")
    result_table.add_column("Arquivo", style="cyan")
    result_table.add_column("Itens", justify="right", style="green")
    result_table.add_column("Tamanho", justify="right", style="yellow")
    
    for filename, count, size in files_created:
        result_table.add_row(filename, str(count), f"{size/1024:.1f} KB")
    
    console.print(result_table)
    console.print(f"\n[green]Arquivos salvos em: {output_dir}[/green]")


def convert_file_by_module():
    """Converte arquivo gerando múltiplos arquivos por módulo (prefixo de tabela)."""
    input_file = get_input_file()
    if not input_file:
        return
    
    # Pasta de saída
    output_dir = Prompt.ask(
        "[bold cyan]Pasta de saída[/bold cyan]",
        default="output_por_modulo"
    )
    
    os.makedirs(output_dir, exist_ok=True)
    
    console.print()
    console.print("[bold yellow]═══ PROCESSANDO ═══[/bold yellow]")
    console.print()
    
    # Parsear
    parser = DumpParser(console)
    tables = parser.parse_file(input_file)
    
    formatter = RagFormatter()
    
    # Agrupar tabelas por prefixo (módulo)
    modules = {}
    for table in tables.values():
        # Extrair prefixo (2-3 primeiros caracteres antes de maiúscula ou underscore)
        name = table.name.upper()
        prefix = ""
        
        # Prefixos conhecidos
        known_prefixes = {
            "EF": "escrita_fiscal",
            "CT": "contabil", 
            "CTB": "contabil",
            "FO": "folha",
            "PT": "patrimonio",
            "GE": "geral",
            "AU": "auditoria",
            "PR": "processos",
            "HO": "honorarios",
            "RE": "registro",
            "TD": "tributos",
            "IM": "imobilizado"
        }
        
        # Tentar encontrar prefixo conhecido
        for pref, mod_name in known_prefixes.items():
            if name.startswith(pref):
                prefix = mod_name
                break
        
        if not prefix:
            # Usar primeiros 2 caracteres como prefixo genérico
            prefix = name[:2].lower() if len(name) >= 2 else "outros"
        
        if prefix not in modules:
            modules[prefix] = {}
        modules[prefix][table.full_name.lower()] = table
    
    files_created = []
    
    # Gerar arquivo por módulo
    for module_name, module_tables in sorted(modules.items()):
        output = formatter.format_tables(module_tables)
        filename = f"{module_name}_tabelas.txt"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(output)
        
        files_created.append((filename, len(module_tables), len(output)))
    
    # Mostrar resultado
    console.print()
    result_table = RichTable(title="Arquivos Gerados por Módulo")
    result_table.add_column("Arquivo", style="cyan")
    result_table.add_column("Tabelas", justify="right", style="green")
    result_table.add_column("Tamanho", justify="right", style="yellow")
    
    for filename, count, size in sorted(files_created):
        result_table.add_row(filename, str(count), f"{size/1024:.1f} KB")
    
    console.print(result_table)
    console.print(f"\n[green]Arquivos salvos em: {output_dir}[/green]")


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
    functions = parser.functions
    procedures = parser.procedures
    
    # Estatísticas por schema (tabelas)
    schemas = {}
    for table in tables.values():
        if table.schema not in schemas:
            schemas[table.schema] = {"tabelas": 0, "fks": 0, "idx": 0}
        schemas[table.schema]["tabelas"] += 1
        schemas[table.schema]["fks"] += len(table.foreign_keys)
        schemas[table.schema]["idx"] += len(table.indexes)
    
    console.print()
    
    # Tabela de schemas
    stats_table = RichTable(title="Tabelas por Schema")
    stats_table.add_column("Schema", style="cyan")
    stats_table.add_column("Tabelas", justify="right", style="green")
    stats_table.add_column("FKs", justify="right", style="yellow")
    stats_table.add_column("Índices", justify="right", style="blue")
    
    total_tables = 0
    total_fks = 0
    total_idx = 0
    
    for schema, counts in sorted(schemas.items()):
        stats_table.add_row(schema, str(counts["tabelas"]), str(counts["fks"]), str(counts["idx"]))
        total_tables += counts["tabelas"]
        total_fks += counts["fks"]
        total_idx += counts["idx"]
    
    stats_table.add_row("[bold]TOTAL[/bold]", f"[bold]{total_tables}[/bold]", 
                        f"[bold]{total_fks}[/bold]", f"[bold]{total_idx}[/bold]")
    
    console.print(stats_table)
    
    # Resumo geral
    console.print()
    summary = RichTable.grid(padding=1)
    summary.add_column(style="cyan", justify="right")
    summary.add_column(style="white")
    
    summary.add_row("⚡ Funções encontradas:", str(len(functions)))
    summary.add_row("📦 Procedures encontradas:", str(len(procedures)))
    
    panel = Panel(summary, title="[bold cyan]Objetos Programáveis[/bold cyan]", border_style="cyan")
    console.print(panel)


def show_rag_config():
    """Mostra configurações recomendadas para RAG."""
    console.print()
    
    config_text = """
## Configurações Recomendadas para Open Arena

Após gerar os arquivos otimizados, configure sua chain com:

### RAG Settings (BYOD)
| Parâmetro | Valor |
|-----------|-------|
| Chunk Size | **512-1024** (recomendado pelo suporte) |
| Chunk Overlap | **10-15%** |
| Size (top_k) | **10-20** |

### Model Settings
| Parâmetro | Valor |
|-----------|-------|
| Temperature | **0.2** |
| Enable Reasoning | **On** |

### Dicas
- Use arquivos menores (por módulo) para melhor precisão
- Formato UTF-8 é obrigatório
- Arquivos de até 100MB cada
- Teste após indexação
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
            convert_file_by_type()
        elif choice == "3":
            convert_file_by_module()
        elif choice == "4":
            show_file_stats()
        elif choice == "5":
            show_rag_config()
        elif choice == "6":
            show_help()
        
        console.print()
        input("Pressione ENTER para continuar...")


if __name__ == '__main__':
    main()

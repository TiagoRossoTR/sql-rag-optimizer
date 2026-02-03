#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQL Dump to RAG Converter

Converte dump do SQL Anywhere (dbunload) para formato otimizado para RAG.
Extrai estrutura de tabelas em formato compacto e legível.

Uso:
    python convert_dump_to_rag.py entrada.txt saida_rag.txt

Autor: TiagoRossoTR
"""

import re
import sys
import argparse
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from pathlib import Path


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


class DumpParser:
    """Parser para arquivos de dump do SQL Anywhere."""
    
    def __init__(self):
        self.tables: Dict[str, Table] = {}
        self.current_content = ""
        
    def parse_file(self, filepath: str) -> Dict[str, Table]:
        """Lê e parseia o arquivo de dump."""
        print(f"Lendo arquivo: {filepath}")
        
        with open(filepath, 'r', encoding='windows-1252') as f:
            self.current_content = f.read()
        
        print(f"Tamanho do arquivo: {len(self.current_content):,} caracteres")
        
        # Extrair CREATE TABLEs
        self._parse_create_tables()
        
        # Extrair COMMENTs
        self._parse_comments()
        
        print(f"Tabelas encontradas: {len(self.tables)}")
        
        return self.tables
    
    def _parse_create_tables(self):
        """Extrai definições de CREATE TABLE."""
        # Regex para CREATE TABLE
        pattern = r'CREATE\s+TABLE\s+"([^"]+)"\."([^"]+)"\s*\((.*?)\)\s*(?:go|;)'
        
        matches = re.findall(pattern, self.current_content, re.DOTALL | re.IGNORECASE)
        
        for schema, table_name, columns_def in matches:
            table = Table(schema=schema, name=table_name)
            
            # Parsear colunas
            self._parse_columns(table, columns_def)
            
            self.tables[table.full_name.lower()] = table
    
    def _parse_columns(self, table: Table, columns_def: str):
        """Extrai definições de colunas."""
        # Separar por vírgulas (cuidando com vírgulas dentro de parênteses)
        lines = self._split_columns(columns_def)
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Ignorar constraints (PRIMARY KEY, FOREIGN KEY, etc)
            if re.match(r'^\s*(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|CONSTRAINT)', line, re.IGNORECASE):
                # Extrair PRIMARY KEY
                pk_match = re.search(r'PRIMARY\s+KEY\s*\(([^)]+)\)', line, re.IGNORECASE)
                if pk_match:
                    pk_cols = [c.strip().strip('"') for c in pk_match.group(1).split(',')]
                    table.primary_key = pk_cols
                    # Marcar colunas como PK
                    for col in table.columns:
                        if col.name in pk_cols:
                            col.is_pk = True
                continue
            
            # Parsear coluna normal
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


class RagFormatter:
    """Formata tabelas para output otimizado para RAG."""
    
    SEPARATOR = "=" * 80
    SUBSEPARATOR = "-" * 80
    
    def format_tables(self, tables: Dict[str, Table]) -> str:
        """Formata todas as tabelas para output RAG."""
        output_parts = []
        
        # Ordenar por nome completo
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
        lines.append("")  # Linha em branco entre tabelas
        
        return "\n".join(lines)
    
    def _format_column(self, col: Column) -> str:
        """Formata uma coluna."""
        parts = [f"- {col.name}"]
        
        # Tipo e nullable
        nullable_str = "NULL" if col.nullable else "NOT NULL"
        parts.append(f"({col.data_type} {nullable_str})")
        
        # Indicadores
        indicators = []
        if col.is_pk:
            indicators.append("PK")
        
        if indicators:
            parts.append(f"[{', '.join(indicators)}]")
        
        # Comentário
        if col.comment:
            parts.append(f"- {col.comment}")
        
        return " ".join(parts)


def main():
    """Função principal."""
    parser = argparse.ArgumentParser(
        description='Converte dump SQL Anywhere para formato otimizado para RAG'
    )
    parser.add_argument('input_file', help='Arquivo de dump de entrada')
    parser.add_argument('output_file', help='Arquivo de saída otimizado')
    parser.add_argument('--schema', help='Filtrar por schema específico', default=None)
    parser.add_argument('--encoding', help='Encoding do arquivo de entrada', default='windows-1252')
    
    args = parser.parse_args()
    
    # Verificar arquivo de entrada
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"ERRO: Arquivo não encontrado: {args.input_file}")
        sys.exit(1)
    
    # Parsear dump
    dump_parser = DumpParser()
    tables = dump_parser.parse_file(args.input_file)
    
    # Filtrar por schema se especificado
    if args.schema:
        tables = {
            k: v for k, v in tables.items() 
            if v.schema.lower() == args.schema.lower()
        }
        print(f"Tabelas após filtro de schema '{args.schema}': {len(tables)}")
    
    # Formatar para RAG
    formatter = RagFormatter()
    output = formatter.format_tables(tables)
    
    # Salvar arquivo (ANSI/Windows-1252 para compatibilidade)
    output_path = Path(args.output_file)
    with open(output_path, 'w', encoding='windows-1252') as f:
        f.write(output)
    
    print(f"\nArquivo gerado: {args.output_file}")
    print(f"Tamanho: {len(output):,} caracteres")
    print(f"Tabelas: {len(tables)}")


if __name__ == '__main__':
    main()

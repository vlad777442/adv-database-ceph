#!/usr/bin/env python3
"""
Command-line interface for Ceph Semantic Storage System.

This CLI provides commands for indexing, searching, and managing
semantic storage of RADOS objects.
"""

import click
import yaml
import logging
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress
from rich import print as rprint
from datetime import datetime

try:
    from core.rados_client import RadosClient
    HAS_RADOS = True
except (ImportError, ModuleNotFoundError):
    HAS_RADOS = False
    RadosClient = None

from core.embedding_generator import EmbeddingGenerator
from core.content_processor import ContentProcessor
from core.rados_vector_store import RadosVectorStore
from services.indexer import Indexer
from services.searcher import Searcher
from services.watcher import Watcher

# Initialize console for rich output
console = Console()

# Default config path
DEFAULT_CONFIG = "config.yaml"


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        sys.exit(1)


def setup_logging(config: dict) -> None:
    """Setup logging configuration."""
    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO'))
    log_format = log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_config.get('file', 'semantic_storage.log'))
        ]
    )


def create_components(config: dict):
    """Create and initialize all system components."""
    # RADOS Client
    rados_config = config['ceph']
    rados_client = RadosClient(
        config_file=rados_config['config_file'],
        client_name=rados_config['client_name'],
        cluster_name=rados_config['cluster_name'],
        pool_name=rados_config['pool_name']
    )
    
    # Embedding Generator
    emb_config = config['embedding']
    embedding_gen = EmbeddingGenerator(
        model_name=emb_config['model'],
        device=emb_config['device'],
        normalize_embeddings=emb_config['normalize_embeddings'],
        batch_size=emb_config['batch_size']
    )
    
    # Content Processor
    idx_config = config['indexing']
    content_processor = ContentProcessor(
        max_file_size_mb=idx_config['max_file_size_mb'],
        encoding_detection=idx_config['encoding_detection'],
        fallback_encoding=idx_config['fallback_encoding'],
        supported_extensions=idx_config['supported_extensions']
    )
    
    # Vector Store
    vec_config = config['vectordb']
    vector_store = RadosVectorStore(
        rados_client=rados_client,
        embedding_dim=vec_config.get('embedding_dim', 384),
    )
    
    return rados_client, embedding_gen, content_processor, vector_store


@click.group()
@click.option('--config', default=DEFAULT_CONFIG, help='Path to configuration file')
@click.pass_context
def cli(ctx, config):
    """Ceph Semantic Storage - Semantic search for RADOS objects."""
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config
    ctx.obj['config'] = load_config(config)
    setup_logging(ctx.obj['config'])


@cli.command()
@click.option('--prefix', help='Only index objects with this prefix')
@click.option('--limit', type=int, help='Maximum number of objects to index')
@click.option('--force', is_flag=True, help='Force reindex of existing objects')
@click.pass_context
def index(ctx, prefix, limit, force):
    """Index objects from the Ceph pool."""
    config = ctx.obj['config']
    
    console.print("\n[bold cyan]🔍 Starting Indexing Process[/bold cyan]\n")
    
    try:
        # Create components
        rados_client, embedding_gen, content_processor, vector_store = create_components(config)
        
        # Connect to Ceph
        console.print("📡 Connecting to Ceph cluster...")
        rados_client.connect()
        console.print(f"✅ Connected to pool: [green]{rados_client.pool_name}[/green]\n")
        
        # Create indexer
        indexer = Indexer(
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            content_processor=content_processor,
            vector_store=vector_store,
            batch_size=config['indexing']['batch_size']
        )
        
        # Run indexing
        stats = indexer.index_pool(
            prefix=prefix,
            limit=limit,
            force_reindex=force,
            show_progress=True
        )
        
        # Display results
        console.print("\n[bold green]✅ Indexing Complete![/bold green]\n")
        
        table = Table(title="Indexing Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Objects", str(stats.total_objects))
        table.add_row("Successfully Indexed", str(stats.successfully_indexed))
        table.add_row("Skipped", str(stats.skipped))
        table.add_row("Failed", str(stats.failed))
        table.add_row("Total Size", f"{stats.total_size_bytes / (1024**2):.2f} MB")
        table.add_row("Duration", f"{stats.duration_seconds:.2f}s")
        
        console.print(table)
        
        if stats.errors:
            console.print(f"\n[yellow]⚠ {len(stats.errors)} errors occurred[/yellow]")
            for error in stats.errors[:5]:  # Show first 5 errors
                console.print(f"  • {error}")
        
        rados_client.disconnect()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument('query')
@click.option('--top-k', default=10, help='Number of results to return')
@click.option('--min-score', default=0.0, help='Minimum relevance score (0-1)')
@click.option('--pool', help='Filter by pool name')
@click.option('--type', 'content_type', help='Filter by content type')
@click.option('--content', is_flag=True, help='Include full content in results')
@click.pass_context
def search(ctx, query, top_k, min_score, pool, content_type, content):
    """Search for objects using natural language query."""
    config = ctx.obj['config']
    
    console.print(f"\n[bold cyan]🔎 Searching for:[/bold cyan] '{query}'\n")
    
    try:
        # Create components
        rados_client, embedding_gen, content_processor, vector_store = create_components(config)
        
        # Connect to Ceph
        rados_client.connect()
        
        # Create searcher
        searcher = Searcher(
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            vector_store=vector_store
        )
        
        # Perform search
        results = searcher.search(
            query_text=query,
            top_k=top_k,
            min_score=min_score,
            pool_name=pool,
            content_type=content_type,
            include_content=content
        )
        
        # Display results
        if not results:
            console.print("[yellow]No results found.[/yellow]")
            return
        
        console.print(f"[green]Found {len(results)} results:[/green]\n")
        
        for i, result in enumerate(results, 1):
            console.print(f"[bold cyan]{i}. {result.object_name}[/bold cyan]")
            console.print(f"   Score: [green]{result.relevance_score:.3f}[/green]")
            console.print(f"   Pool: {result.pool_name}")
            console.print(f"   Type: {result.content_type}")
            console.print(f"   Size: {result.size_bytes / 1024:.1f} KB")
            
            if result.keywords:
                console.print(f"   Keywords: {', '.join(result.keywords[:5])}")
            
            console.print(f"   Preview: {result.content_preview[:200]}...")
            
            if content and result.full_content:
                console.print(f"\n   [dim]Full Content:[/dim]\n{result.full_content[:500]}...\n")
            
            console.print()
        
        rados_client.disconnect()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option('--duration', type=int, help='Watch duration in seconds (default: infinite)')
@click.option('--daemon', is_flag=True, help='Run as daemon process')
@click.pass_context
def watch(ctx, duration, daemon):
    """Watch pool for changes and auto-index new objects."""
    config = ctx.obj['config']
    
    console.print("\n[bold cyan]👁 Starting Watcher Service[/bold cyan]\n")
    
    try:
        # Create components
        rados_client, embedding_gen, content_processor, vector_store = create_components(config)
        
        # Connect to Ceph
        console.print("📡 Connecting to Ceph cluster...")
        rados_client.connect()
        console.print(f"✅ Watching pool: [green]{rados_client.pool_name}[/green]\n")
        
        # Create indexer and watcher
        indexer = Indexer(
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            content_processor=content_processor,
            vector_store=vector_store
        )
        
        watcher_config = config.get('watcher', {})
        watcher = Watcher(
            rados_client=rados_client,
            indexer=indexer,
            poll_interval=watcher_config.get('poll_interval_seconds', 60)
        )
        
        console.print(f"⏱ Poll interval: {watcher.poll_interval} seconds")
        console.print("Press Ctrl+C to stop\n")
        
        # Run watcher
        if daemon:
            log_file = watcher_config.get('log_file', './watcher.log')
            watcher.watch_daemon(log_file=log_file)
        else:
            watcher.watch(duration=duration)
        
        rados_client.disconnect()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]⏹ Watcher stopped by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_context
def stats(ctx):
    """Display system statistics."""
    config = ctx.obj['config']
    
    console.print("\n[bold cyan]📊 System Statistics[/bold cyan]\n")
    
    try:
        # Create components
        rados_client, embedding_gen, content_processor, vector_store = create_components(config)
        
        # Connect to Ceph
        rados_client.connect()
        
        # Get cluster stats
        cluster_stats = rados_client.get_cluster_stats()
        pools = rados_client.list_pools()
        
        # Get vector store stats
        vec_stats = vector_store.get_stats()
        
        # Display Ceph stats
        table = Table(title="Ceph Cluster")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Space", f"{cluster_stats['kb'] / (1024**2):.2f} GB")
        table.add_row("Used Space", f"{cluster_stats['kb_used'] / (1024**2):.2f} GB")
        table.add_row("Available Space", f"{cluster_stats['kb_avail'] / (1024**2):.2f} GB")
        table.add_row("Total Objects", str(cluster_stats['num_objects']))
        table.add_row("Pools", ", ".join(pools))
        
        console.print(table)
        console.print()
        
        # Display vector store stats
        table2 = Table(title="Vector Store")
        table2.add_column("Metric", style="cyan")
        table2.add_column("Value", style="green")
        
        table2.add_row("Backend", vec_stats.get('backend', 'rados_xattr'))
        table2.add_row("Indexed Objects", str(vec_stats.get('indexed_objects', vec_stats.get('total_objects', 0))))
        table2.add_row("Embedding Dim", str(vec_stats.get('embedding_dim', '')))
        table2.add_row("Total Embedding KB", f"{vec_stats.get('total_embedding_kb', 0):.1f}")
        
        console.print(table2)
        console.print()
        
        # Display model info
        model_info = embedding_gen.get_model_info()
        table3 = Table(title="Embedding Model")
        table3.add_column("Property", style="cyan")
        table3.add_column("Value", style="green")
        
        for key, value in model_info.items():
            table3.add_row(key.replace('_', ' ').title(), str(value))
        
        console.print(table3)
        
        rados_client.disconnect()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument('object_name')
@click.option('--top-k', default=5, help='Number of similar objects to find')
@click.pass_context
def similar(ctx, object_name, top_k):
    """Find objects similar to a given object."""
    config = ctx.obj['config']
    
    console.print(f"\n[bold cyan]🔍 Finding similar objects to:[/bold cyan] {object_name}\n")
    
    try:
        # Create components
        rados_client, embedding_gen, content_processor, vector_store = create_components(config)
        
        # Connect to Ceph
        rados_client.connect()
        
        # Create searcher
        searcher = Searcher(
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            vector_store=vector_store
        )
        
        # Find similar objects
        results = searcher.find_similar(object_name, top_k=top_k)
        
        if not results:
            console.print("[yellow]No similar objects found.[/yellow]")
            return
        
        console.print(f"[green]Found {len(results)} similar objects:[/green]\n")
        
        for i, result in enumerate(results, 1):
            console.print(f"[bold cyan]{i}. {result.object_name}[/bold cyan]")
            console.print(f"   Similarity: [green]{result.relevance_score:.3f}[/green]")
            console.print(f"   Preview: {result.content_preview[:150]}...")
            console.print()
        
        rados_client.disconnect()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument('file_path', type=click.Path(exists=True))
@click.option('--name', help='Custom object name in Ceph (default: filename)')
@click.option('--description', '-d', help='Description of the file (improves LLM metadata)')
@click.option('--index/--no-index', default=True, help='Index after upload (default: yes)')
@click.option('--llm/--no-llm', default=True, help='Use LLM for metadata generation (default: yes)')
@click.pass_context
def upload(ctx, file_path: str, name: str, description: str, index: bool, llm: bool):
    """
    Upload a file to Ceph with LLM-generated metadata.
    
    Uploads a local file to the Ceph pool and optionally generates rich metadata
    (summary, keywords, tags) using an LLM for better semantic search.
    
    Examples:
    
        ./run.sh upload myfile.txt
        
        ./run.sh upload report.pdf --description "Q3 financial report"
        
        ./run.sh upload code.py --name src/utils/code.py
        
        ./run.sh upload data.csv --no-llm
    """
    config = ctx.obj['config']
    
    # Resolve file path and name
    file_path_obj = Path(file_path)
    object_name = name or file_path_obj.name
    
    console.print(f"\n[bold cyan]📤 Uploading:[/bold cyan] {file_path}")
    console.print(f"[bold cyan]   Target:[/bold cyan] {object_name}\n")
    
    try:
        # Read file content
        with open(file_path, 'rb') as f:
            data = f.read()
        
        file_size = len(data)
        console.print(f"📦 File size: {file_size / 1024:.1f} KB")
        
        # Create components
        rados_client, embedding_gen, content_processor, vector_store = create_components(config)
        
        # Connect to Ceph
        console.print("📡 Connecting to Ceph...")
        rados_client.connect()
        console.print(f"✅ Connected to pool: [green]{rados_client.pool_name}[/green]\n")
        
        # Check if object already exists
        if rados_client.object_exists(object_name):
            console.print(f"[yellow]⚠ Object '{object_name}' already exists. Overwriting...[/yellow]")
        
        # Upload to Ceph
        console.print("📤 Writing to Ceph...")
        rados_client.write_object(object_name, data)
        console.print(f"✅ Uploaded: [green]{object_name}[/green]\n")
        
        # Index if requested
        if index:
            console.print("[bold cyan]🔍 Indexing with semantic metadata...[/bold cyan]")
            
            # Try to extract text content
            try:
                text_content, encoding = content_processor.extract_text(data, object_name)
            except ValueError as e:
                console.print(f"[yellow]⚠ Cannot extract text: {e}[/yellow]")
                console.print("[yellow]   Skipping indexing for binary file.[/yellow]")
                rados_client.disconnect()
                return
            
            # Create indexer
            indexer = Indexer(
                rados_client=rados_client,
                embedding_generator=embedding_gen,
                content_processor=content_processor,
                vector_store=vector_store
            )
            
            # Get LLM config if using LLM
            llm_config = config.get('llm', {}) if llm else None
            
            if llm and llm_config.get('agent_enabled', False):
                console.print("🤖 Generating metadata with LLM...")
            
            # Index with LLM metadata
            metadata = indexer.index_with_llm_metadata(
                object_name=object_name,
                content=text_content,
                size_bytes=file_size,
                llm_config=llm_config if llm else None,
                user_description=description,
                use_llm=llm and llm_config.get('agent_enabled', False)
            )
            
            if metadata:
                console.print(f"✅ Indexed successfully!\n")
                
                # Display metadata
                table = Table(title="Generated Metadata")
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="green")
                
                table.add_row("Object Name", metadata.object_name)
                table.add_row("Size", f"{metadata.size_bytes / 1024:.1f} KB")
                table.add_row("Content Type", metadata.content_type)
                
                if metadata.summary:
                    # Truncate long summaries for display
                    summary_display = metadata.summary[:150] + "..." if len(metadata.summary) > 150 else metadata.summary
                    table.add_row("Summary", summary_display)
                
                if metadata.keywords:
                    table.add_row("Keywords", ", ".join(metadata.keywords[:7]))
                
                if metadata.tags:
                    table.add_row("Tags", ", ".join(metadata.tags))
                
                console.print(table)
            else:
                console.print("[yellow]⚠ Indexing completed with warnings[/yellow]")
        else:
            console.print("[dim]Skipping indexing (--no-index)[/dim]")
        
        rados_client.disconnect()
        console.print(f"\n[bold green]✅ Upload complete![/bold green]")
        
    except FileNotFoundError:
        console.print(f"\n[red]❌ File not found: {file_path}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.argument('prompt', required=False)
@click.option('--auto-confirm', '-y', is_flag=True, help='Auto-confirm destructive operations')
@click.pass_context
def execute(ctx, prompt: str, auto_confirm: bool):
    """
    Execute a single natural language command.
    
    Example: ./run.sh execute "search for files about greetings"
    """
    if not prompt:
        console.print("[red]Error: Prompt required[/red]")
        console.print("Usage: cli.py execute \"your natural language command\"")
        sys.exit(1)
    
    try:
        config = ctx.obj['config']
        
        # Check if agent is enabled
        llm_config = config.get('llm', {})
        if not llm_config.get('agent_enabled', False):
            console.print("[red]Error: LLM agent is not enabled in config.yaml[/red]")
            console.print("Set llm.agent_enabled: true in config.yaml")
            sys.exit(1)
        
        console.print(f"\n[bold cyan]🤖 Processing:[/bold cyan] {prompt}\n")
        
        # Initialize components
        from services.agent_service import AgentService
        
        rados_client = RadosClient(**config['ceph'])
        
        # Map embedding config properly
        emb_config = config['embedding']
        embedding_gen = EmbeddingGenerator(
            model_name=emb_config.get('model', 'all-MiniLM-L6-v2'),
            device=emb_config.get('device', 'cpu'),
            normalize_embeddings=emb_config.get('normalize_embeddings', True),
            batch_size=emb_config.get('batch_size', 32)
        )
        
        # Map indexing config properly
        idx_config = config['indexing']
        content_proc = ContentProcessor(
            max_file_size_mb=idx_config.get('max_file_size_mb', 100),
            encoding_detection=idx_config.get('encoding_detection', True),
            fallback_encoding=idx_config.get('fallback_encoding', 'utf-8'),
            supported_extensions=idx_config.get('supported_extensions', [])
        )
        
        # Map vectordb config properly
        vec_config = config['vectordb']
        vector_store = RadosVectorStore(
            rados_client=rados_client,
            embedding_dim=vec_config.get('embedding_dim', 384),
        )
        
        rados_client.connect()
        
        # Create agent service
        agent_service = AgentService(
            llm_config=llm_config,
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            content_processor=content_proc,
            vector_store=vector_store
        )
        
        # Execute command
        result = agent_service.execute(prompt, auto_confirm=auto_confirm)
        
        # Display result
        if result.success:
            console.print(f"[green]✅ {result.message}[/green]")
        else:
            console.print(f"[red]❌ {result.message}[/red]")
            if result.error:
                console.print(f"[red]Error: {result.error}[/red]")
        
        # Show execution time
        console.print(f"\n[dim]Execution time: {result.execution_time:.2f}s[/dim]")
        
        rados_client.disconnect()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--history-size', default=10, help='Number of messages to keep in history')
@click.pass_context
def chat(ctx, history_size: int):
    """
    Interactive chat mode with natural language interface.
    
    Chat with the LLM agent to perform operations on Ceph storage.
    Type 'exit', 'quit', or press Ctrl+C to exit.
    """
    try:
        config = ctx.obj['config']
        
        # Check if agent is enabled
        llm_config = config.get('llm', {})
        if not llm_config.get('agent_enabled', False):
            console.print("[red]Error: LLM agent is not enabled in config.yaml[/red]")
            console.print("Set llm.agent_enabled: true in config.yaml")
            sys.exit(1)
        
        console.print("\n[bold cyan]🤖 Ceph Semantic Storage - AI Assistant[/bold cyan]")
        console.print("[dim]Type 'exit' or 'quit' to end the session[/dim]\n")
        
        # Initialize components
        from services.agent_service import AgentService
        
        # Try to initialize RADOS client, fall back to None if not available
        rados_client = None
        if HAS_RADOS:
            try:
                rados_client = RadosClient(**config['ceph'])
                rados_client.connect()
                console.print(f"[green]✅ Connected to pool: {config['ceph']['pool_name']}[/green]\n")
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Could not connect to Ceph: {e}[/yellow]")
                console.print("[yellow]Chat mode will operate without Ceph storage access.[/yellow]\n")
        else:
            console.print("[yellow]⚠️  Ceph RADOS not available. Chat mode will operate without Ceph storage access.[/yellow]\n")
        
        # Map embedding config properly
        emb_config = config['embedding']
        embedding_gen = EmbeddingGenerator(
            model_name=emb_config.get('model', 'all-MiniLM-L6-v2'),
            device=emb_config.get('device', 'cpu'),
            normalize_embeddings=emb_config.get('normalize_embeddings', True),
            batch_size=emb_config.get('batch_size', 32)
        )
        
        # Map indexing config properly
        idx_config = config['indexing']
        content_proc = ContentProcessor(
            max_file_size_mb=idx_config.get('max_file_size_mb', 100),
            encoding_detection=idx_config.get('encoding_detection', True),
            fallback_encoding=idx_config.get('fallback_encoding', 'utf-8'),
            supported_extensions=idx_config.get('supported_extensions', [])
        )
        
        # Map vectordb config properly
        vec_config = config['vectordb']
        vector_store = RadosVectorStore(
            rados_client=rados_client,
            embedding_dim=vec_config.get('embedding_dim', 384),
        )
        
        # Create agent service
        agent_service = AgentService(
            llm_config=llm_config,
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            content_processor=content_proc,
            vector_store=vector_store
        )
        
        agent_service.agent.conversation.max_history = history_size
        
        # Chat loop
        while True:
            try:
                # Get user input
                user_input = console.input("[bold green]You:[/bold green] ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() in ['exit', 'quit', 'q']:
                    console.print("\n[yellow]Goodbye! 👋[/yellow]")
                    break
                
                if user_input.lower() in ['clear', 'reset']:
                    agent_service.clear_history()
                    console.print("[yellow]Conversation history cleared.[/yellow]\n")
                    continue
                
                # Process query
                console.print()
                with console.status("[cyan]Thinking...[/cyan]"):
                    result = agent_service.chat(user_input)
                
                # Check if confirmation needed
                if not result.success and result.metadata.get('requires_user_confirmation'):
                    console.print(f"[yellow]⚠️  This operation requires confirmation:[/yellow]")
                    intent_data = result.metadata.get('intent', {})
                    console.print(f"[yellow]Operation: {intent_data.get('operation')}[/yellow]")
                    console.print(f"[yellow]Parameters: {intent_data.get('parameters')}[/yellow]")
                    
                    confirm = console.input("\n[bold]Proceed? (yes/no):[/bold] ").strip().lower()
                    if confirm in ['yes', 'y']:
                        # Re-execute with auto-confirm
                        with console.status("[cyan]Executing...[/cyan]"):
                            result = agent_service.execute(user_input, auto_confirm=True)
                    else:
                        console.print("[yellow]Operation cancelled.[/yellow]\n")
                        continue
                
                # Display result
                console.print(f"[bold cyan]Assistant:[/bold cyan] ", end="")
                if result.success:
                    console.print(result.message)
                else:
                    console.print(f"[red]{result.message}[/red]")
                    if result.error:
                        console.print(f"[red]Error: {result.error}[/red]")
                
                console.print()
                
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted. Type 'exit' to quit or continue chatting.[/yellow]\n")
                continue
            except EOFError:
                console.print("\n[yellow]Goodbye! 👋[/yellow]")
                break
        
        if rados_client:
            rados_client.disconnect()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.pass_context
def health(ctx):
    """
    Check Ceph cluster health status.
    
    Displays current cluster health, OSD status, and any warnings or errors.
    """
    from core.cluster_manager import CephClusterManager
    
    console.print("\n[bold cyan]🏥 Ceph Cluster Health Check[/bold cyan]\n")
    
    try:
        manager = CephClusterManager()
        
        # Get cluster health
        health = manager.get_cluster_health()
        
        # Display health status with color coding
        status_colors = {
            "HEALTH_OK": "green",
            "HEALTH_WARN": "yellow",
            "HEALTH_ERR": "red"
        }
        color = status_colors.get(health.status, "white")
        
        console.print(f"[bold {color}]Status: {health.status}[/bold {color}]")
        console.print(f"[dim]Timestamp: {health.timestamp}[/dim]\n")
        
        # Display summary
        if health.summary:
            console.print(f"[bold]Summary:[/bold] {health.summary}\n")
        
        # Display health checks if any
        if health.checks:
            console.print("[bold yellow]Health Checks:[/bold yellow]")
            for check_name, check_data in health.checks.items():
                severity = check_data.get('severity', 'UNKNOWN')
                message = check_data.get('summary', {}).get('message', str(check_data))
                sev_color = "red" if severity == "HEALTH_ERR" else "yellow" if severity == "HEALTH_WARN" else "green"
                console.print(f"  [{sev_color}]• {check_name}:[/{sev_color}] {message}")
            console.print()
        
        # Display details if any
        if health.details:
            console.print("[bold]Details:[/bold]")
            for detail in health.details[:10]:
                console.print(f"  • {detail}")
        
        console.print()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        console.print("[dim]Make sure you have Ceph CLI access and proper permissions.[/dim]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.pass_context
def diagnose(ctx):
    """
    Run comprehensive cluster diagnostics.
    
    Analyzes cluster health, OSD status, PG states, and provides recommendations.
    """
    from core.cluster_manager import CephClusterManager
    
    console.print("\n[bold cyan]🔬 Running Cluster Diagnostics...[/bold cyan]\n")
    
    try:
        manager = CephClusterManager()
        
        # Run diagnosis
        with console.status("[cyan]Analyzing cluster...[/cyan]"):
            diagnosis = manager.diagnose_cluster()
        
        # Display overall status
        status_colors = {
            "healthy": "green",
            "warning": "yellow", 
            "critical": "red"
        }
        color = status_colors.get(diagnosis.get('status', 'unknown'), "white")
        console.print(f"[bold {color}]Overall Status: {diagnosis.get('status', 'unknown').upper()}[/bold {color}]\n")
        
        # Display issues
        if diagnosis.get('issues'):
            console.print("[bold yellow]Issues Found:[/bold yellow]")
            for issue in diagnosis['issues']:
                console.print(f"  [yellow]⚠ {issue}[/yellow]")
            console.print()
        else:
            console.print("[green]✅ No issues detected[/green]\n")
        
        # Display recommendations
        if diagnosis.get('recommendations'):
            console.print("[bold cyan]Recommendations:[/bold cyan]")
            for rec in diagnosis['recommendations']:
                console.print(f"  [cyan]💡 {rec}[/cyan]")
            console.print()
        
        # Display capacity info
        if 'capacity' in diagnosis:
            cap = diagnosis['capacity']
            console.print("[bold]Capacity Overview:[/bold]")
            console.print(f"  Total: {cap.get('total_tb', 'N/A')} TB")
            console.print(f"  Used: {cap.get('used_tb', 'N/A')} TB ({cap.get('used_percent', 'N/A')}%)")
            console.print(f"  Available: {cap.get('available_tb', 'N/A')} TB")
            console.print()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--output', '-o', default='evaluation_report.json', help='Output file for report')
@click.option('--categories', '-c', multiple=True, help='Specific categories to test')
@click.option('--quick', is_flag=True, help='Run quick evaluation (subset of tests)')
@click.pass_context
def evaluate(ctx, output: str, categories: tuple, quick: bool):
    """
    Run evaluation framework to assess agent performance.
    
    This runs a comprehensive evaluation of the LLM agent's ability to understand
    and execute natural language commands. Results are saved to a JSON report.
    
    Examples:
    
        ./run.sh evaluate
        
        ./run.sh evaluate --quick
        
        ./run.sh evaluate -c search -c cluster -o my_report.json
    """
    config = ctx.obj['config']
    
    console.print("\n[bold cyan]📊 Running Agent Evaluation Framework[/bold cyan]\n")
    
    try:
        from evaluation._base import EvaluationFramework
        
        # Check if agent is enabled
        llm_config = config.get('llm', {})
        if not llm_config.get('agent_enabled', False):
            console.print("[red]Error: LLM agent is not enabled in config.yaml[/red]")
            console.print("Set llm.agent_enabled: true in config.yaml")
            sys.exit(1)
        
        # Initialize components
        from services.agent_service import AgentService
        
        # Try to connect to RADOS
        rados_client = None
        if HAS_RADOS:
            try:
                rados_client = RadosClient(**config['ceph'])
                rados_client.connect()
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Could not connect to Ceph: {e}[/yellow]")
        
        # Create embedding generator
        emb_config = config['embedding']
        embedding_gen = EmbeddingGenerator(
            model_name=emb_config.get('model', 'all-MiniLM-L6-v2'),
            device=emb_config.get('device', 'cpu'),
            normalize_embeddings=emb_config.get('normalize_embeddings', True),
            batch_size=emb_config.get('batch_size', 32)
        )
        
        # Create other components
        idx_config = config['indexing']
        content_proc = ContentProcessor(
            max_file_size_mb=idx_config.get('max_file_size_mb', 100),
            encoding_detection=idx_config.get('encoding_detection', True),
            fallback_encoding=idx_config.get('fallback_encoding', 'utf-8'),
            supported_extensions=idx_config.get('supported_extensions', [])
        )
        
        vec_config = config['vectordb']
        vector_store = RadosVectorStore(
            rados_client=rados_client,
            embedding_dim=vec_config.get('embedding_dim', 384),
        )
        
        # Create agent service
        agent_service = AgentService(
            llm_config=llm_config,
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            content_processor=content_proc,
            vector_store=vector_store
        )
        
        # Create evaluation framework
        eval_framework = EvaluationFramework(agent=agent_service.agent)
        
        # Filter categories if specified
        category_filter = list(categories) if categories else None
        
        # Run evaluation
        console.print("[cyan]Running tests...[/cyan]")
        console.print(f"Categories: {', '.join(category_filter) if category_filter else 'all'}")
        console.print(f"Mode: {'quick' if quick else 'full'}\n")
        
        with Progress() as progress:
            task = progress.add_task("[cyan]Evaluating...", total=100)
            
            # Run the evaluation
            report = eval_framework.run_evaluation(
                categories=category_filter,
                quick_mode=quick,
                progress_callback=lambda p: progress.update(task, completed=p * 100)
            )
        
        # Display results
        console.print("\n[bold green]✅ Evaluation Complete![/bold green]\n")
        
        # Summary table
        table = Table(title="Evaluation Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Tests", str(report.total_tests))
        table.add_row("Passed", f"[green]{report.passed_tests}[/green]")
        table.add_row("Failed", f"[red]{report.failed_tests}[/red]")
        table.add_row("Intent Accuracy", f"{report.intent_accuracy:.1f}%")
        table.add_row("Parameter Accuracy", f"{report.parameter_accuracy:.1f}%")
        table.add_row("Avg Latency", f"{report.avg_latency_ms:.1f}ms")
        table.add_row("P95 Latency", f"{report.p95_latency_ms:.1f}ms")
        
        console.print(table)
        
        # Save report
        import json
        with open(output, 'w') as f:
            json.dump({
                'timestamp': report.timestamp,
                'total_tests': report.total_tests,
                'passed_tests': report.passed_tests,
                'failed_tests': report.failed_tests,
                'intent_accuracy': report.intent_accuracy,
                'parameter_accuracy': report.parameter_accuracy,
                'response_quality': report.response_quality,
                'avg_latency_ms': report.avg_latency_ms,
                'p50_latency_ms': report.p50_latency_ms,
                'p95_latency_ms': report.p95_latency_ms,
                'p99_latency_ms': report.p99_latency_ms,
                'category_results': report.category_results,
                'results': [vars(r) if hasattr(r, '__dict__') else str(r) for r in report.results]
            }, f, indent=2, default=str)
        console.print(f"\n[dim]Full report saved to: {output}[/dim]")
        
        # Show failed tests if any
        failed_results = [r for r in report.results if not r.success]
        if failed_results:
            console.print(f"\n[yellow]Failed Tests ({len(failed_results)}):[/yellow]")
            for test in failed_results[:10]:
                if test.error:
                    console.print(f"  [red]✗ {test.test_id}[/red]: {test.error}")
                else:
                    console.print(f"  [red]✗ {test.test_id}[/red]: expected '{test.expected_intent}', got '{test.predicted_intent}'")
        
        if rados_client:
            rados_client.disconnect()
        
    except ImportError as e:
        console.print(f"[red]Error: Evaluation framework not found: {e}[/red]")
        console.print("[dim]Make sure the evaluation module is properly installed.[/dim]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.argument('question', required=False)
@click.option('--top-k', default=3, help='Number of documents to retrieve')
@click.pass_context
def ask(ctx, question: str, top_k: int):
    """
    Ask a question about Ceph using the RAG documentation system.
    
    This command uses the built-in Ceph knowledge base and any indexed
    documentation to answer questions about Ceph concepts, troubleshooting,
    and best practices.
    
    Examples:
    
        ./run.sh ask "what is a placement group?"
        
        ./run.sh ask "how do I recover from HEALTH_WARN?"
        
        ./run.sh ask "explain OSD states" --top-k 5
    """
    config = ctx.obj['config']
    
    if not question:
        console.print("[red]Error: Please provide a question[/red]")
        console.print("Usage: ./run.sh ask \"your question about Ceph\"")
        sys.exit(1)
    
    console.print(f"\n[bold cyan]❓ Question:[/bold cyan] {question}\n")
    
    try:
        from core.rag_system import CephDocRAG
        
        # Initialize embedding generator
        emb_config = config['embedding']
        embedding_gen = EmbeddingGenerator(
            model_name=emb_config.get('model', 'all-MiniLM-L6-v2'),
            device=emb_config.get('device', 'cpu'),
            normalize_embeddings=emb_config.get('normalize_embeddings', True),
            batch_size=emb_config.get('batch_size', 32)
        )
        
        # Initialize RAG system
        rag = CephDocRAG(
            embedding_generator=embedding_gen,
            docs_directory="./ceph_docs",
            persist_directory="./rag_data"
        )
        
        # Search for relevant documents
        with console.status("[cyan]Searching knowledge base...[/cyan]"):
            results = rag.search(question, top_k=top_k)
            context = rag.get_context_for_query(question, top_k=top_k)
        
        if not results:
            console.print("[yellow]No relevant documentation found for this question.[/yellow]")
            sys.exit(0)
        
        console.print("[bold green]📚 Relevant Documentation:[/bold green]\n")
        
        for i, result in enumerate(results, 1):
            score_color = "green" if result.score > 0.5 else "yellow" if result.score > 0.3 else "dim"
            console.print(f"[bold cyan]{i}. {result.document.title}[/bold cyan]")
            console.print(f"   [{score_color}]Relevance: {result.score:.2%}[/{score_color}]")
            console.print(f"   [dim]Section: {result.document.section}[/dim]")
            console.print(f"   [dim]Source: {result.document.source}[/dim]")
            
            # Show content preview
            content_preview = result.document.content[:300]
            if len(result.document.content) > 300:
                content_preview += "..."
            console.print(f"\n   {content_preview}\n")
        
        # Show how to get LLM-powered answers
        llm_config = config.get('llm', {})
        if llm_config.get('agent_enabled', False):
            console.print("[dim]Tip: Use 'chat' mode for LLM-powered answers that synthesize this documentation.[/dim]")
        
        console.print()
        
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

@cli.command()
@click.option('--runs', '-n', default=5, help='Number of evaluation runs')
@click.option('--expanded', is_flag=True, help='Use expanded 100+ test suite')
@click.option('--scalability', is_flag=True, help='Run scalability benchmarks')
@click.option('--cli-baseline', is_flag=True, help='Run CLI baseline comparison')
@click.option('--models', '-m', multiple=True, help='Models to compare (e.g., -m llama3.2 -m llama3.1)')
@click.option('--latex', is_flag=True, help='Generate LaTeX tables for paper')
@click.option('--output-dir', default='./evaluation_results/benchmarks', help='Output directory')
@click.pass_context
def benchmark(ctx, runs, expanded, scalability, cli_baseline, models, latex, output_dir):
    """
    Run comprehensive benchmarks for paper evaluation.

    Multi-run evaluation with statistics, scalability analysis,
    CLI baselines, and multi-model comparison.

    Examples:

        ./run.sh benchmark --runs 5

        ./run.sh benchmark --expanded --runs 3 --latex

        ./run.sh benchmark --scalability --cli-baseline

        ./run.sh benchmark -m llama3.2 -m llama3.1 --runs 3
    """
    config = ctx.obj['config']

    console.print("\n[bold cyan]🔬 Running Comprehensive Benchmarks[/bold cyan]\n")

    try:
        from evaluation._base import EvaluationFramework
        from services.agent_service import AgentService

        # Initialize components
        rados_client = None
        if HAS_RADOS:
            try:
                rados_client = RadosClient(**config['ceph'])
                rados_client.connect()
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Could not connect to Ceph: {e}[/yellow]")

        emb_config = config['embedding']
        embedding_gen = EmbeddingGenerator(
            model_name=emb_config.get('model', 'all-MiniLM-L6-v2'),
            device=emb_config.get('device', 'cpu'),
            normalize_embeddings=emb_config.get('normalize_embeddings', True),
            batch_size=emb_config.get('batch_size', 32)
        )

        idx_config = config['indexing']
        content_proc = ContentProcessor(
            max_file_size_mb=idx_config.get('max_file_size_mb', 100),
            encoding_detection=idx_config.get('encoding_detection', True),
            fallback_encoding=idx_config.get('fallback_encoding', 'utf-8'),
            supported_extensions=idx_config.get('supported_extensions', [])
        )

        vec_config = config['vectordb']
        vector_store = RadosVectorStore(
            rados_client=rados_client,
            embedding_dim=vec_config.get('embedding_dim', 384),
        )

        llm_config = config.get('llm', {})
        agent_service = AgentService(
            llm_config=llm_config,
            rados_client=rados_client,
            embedding_generator=embedding_gen,
            content_processor=content_proc,
            vector_store=vector_store
        )

        # Setup test data for benchmarks
        if rados_client:
            console.print("\n[bold]📦 Setting up test data...[/bold]")
            from evaluation.test_data_setup import setup_test_data, verify_test_data
            
            indexer = Indexer(
                rados_client=rados_client,
                embedding_generator=embedding_gen,
                content_processor=content_proc,
                vector_store=vector_store
            )
            
            created, indexed, errors = setup_test_data(rados_client, indexer)
            console.print(f"[green]✅ Test data ready: {created} objects created, {indexed} indexed[/green]")
            
            if errors:
                console.print(f"[yellow]⚠️  {len(errors)} errors during setup[/yellow]")
                for error in errors[:3]:  # Show first 3 errors
                    console.print(f"  [dim]{error}[/dim]")
            
            # Verify setup
            verification = verify_test_data(rados_client, vector_store)
            if not verification["ready"]:
                console.print("[yellow]⚠️  Warning: Test data verification failed[/yellow]")
                if verification["missing_from_rados"]:
                    console.print(f"  Missing from RADOS: {verification['missing_from_rados']}")
                if verification["missing_from_index"]:
                    console.print(f"  Missing from index: {verification['missing_from_index']}")
        else:
            console.print("[yellow]⚠️  Warning: No RADOS connection, skipping test data setup[/yellow]")

        # Expanded test suite has been consolidated into evaluation/test_cases.py
        if expanded:
            from evaluation._base import EvaluationFramework
            console.print("[cyan]Note: Use 'python -m evaluation.runner --intent' for the full test suite.[/cyan]")

        # Create benchmark suite
        bench_config = BenchmarkConfig(
            num_runs=runs,
            output_dir=output_dir,
            models=list(models) if models else [llm_config.get('model', 'llama3.2')],
        )
        suite = BenchmarkSuite(bench_config)

        # 1. Multi-run evaluation
        console.print(f"\n[bold]📊 Multi-run evaluation ({runs} runs)...[/bold]")

        def run_progress(run_id, total):
            console.print(f"  Run {run_id}/{total}...")

        multi_run_results = suite.run_multi_evaluation(
            agent_service.agent, num_runs=runs, progress_callback=run_progress
        )

        # Display results
        table = Table(title=f"Multi-Run Results ({runs} runs)")
        table.add_column("Metric", style="cyan")
        table.add_column("Mean ± Std", style="green")
        table.add_row("Intent Accuracy", f"{multi_run_results.intent_accuracy_mean:.1f}% ± {multi_run_results.intent_accuracy_std:.1f}%")
        table.add_row("Parameter Accuracy", f"{multi_run_results.parameter_accuracy_mean:.1f}% ± {multi_run_results.parameter_accuracy_std:.1f}%")
        table.add_row("Response Quality", f"{multi_run_results.response_quality_mean:.1f}% ± {multi_run_results.response_quality_std:.1f}%")
        table.add_row("Avg Latency (ms)", f"{multi_run_results.avg_latency_mean:.0f} ± {multi_run_results.avg_latency_std:.0f}")
        table.add_row("P95 Latency (ms)", f"{multi_run_results.p95_latency_mean:.0f} ± {multi_run_results.p95_latency_std:.0f}")
        console.print(table)

        # 2. Scalability benchmarks (optional)
        scalability_results = None
        if scalability and rados_client:
            console.print("\n[bold]📈 Scalability benchmarks...[/bold]")
            indexer = Indexer(
                rados_client=rados_client,
                embedding_generator=embedding_gen,
                content_processor=content_proc,
                vector_store=vector_store
            )
            searcher = Searcher(
                vector_store=vector_store,
                embedding_generator=embedding_gen
            )
            scalability_results = suite.run_scalability_benchmark(
                rados_client=rados_client,
                embedding_generator=embedding_gen,
                vector_store=vector_store,
                searcher=searcher,
                sizes=[10, 50, 100, 500],
            )
            scale_table = Table(title="Scalability Results")
            scale_table.add_column("Objects", style="cyan")
            scale_table.add_column("Index (ms)", style="green")
            scale_table.add_column("Throughput (obj/s)", style="green")
            scale_table.add_column("Search (ms)", style="green")
            for sr in scalability_results:
                scale_table.add_row(
                    str(sr.num_objects),
                    f"{sr.indexing_time_ms:.0f}",
                    f"{sr.indexing_throughput_ops:.1f}",
                    f"{sr.search_latency_ms:.1f} ± {sr.search_latency_std:.1f}"
                )
            console.print(scale_table)

        # 3. CLI baseline (optional)
        cli_results = None
        if cli_baseline:
            console.print("\n[bold]⚡ CLI baseline comparison...[/bold]")
            cli_results = suite.run_cli_comparison(
                agent_service.agent, rados_client=rados_client
            )
            cli_table = Table(title="Agent vs CLI Latency")
            cli_table.add_column("Operation", style="cyan")
            cli_table.add_column("Agent (ms)", style="yellow")
            cli_table.add_column("CLI (ms)", style="green")
            cli_table.add_column("Overhead", style="red")
            for c in cli_results:
                cli_table.add_row(
                    c.operation,
                    f"{c.agent_latency_ms:.0f}",
                    f"{c.cli_latency_ms:.0f}",
                    f"{c.overhead_percent:.0f}%"
                )
            console.print(cli_table)

        # 4. Multi-model comparison (optional)
        model_results = None
        if models and len(models) > 1:
            console.print(f"\n[bold]🤖 Multi-model comparison: {list(models)}...[/bold]")
            model_results = suite.run_model_comparison(
                rados_client=rados_client,
                indexer=Indexer(
                    rados_client=rados_client,
                    embedding_generator=embedding_gen,
                    content_processor=content_proc,
                    vector_store=vector_store
                ) if rados_client else None,
                searcher=Searcher(vector_store=vector_store, embedding_generator=embedding_gen),
                vector_store=vector_store,
                models=list(models),
                num_runs=min(runs, 3),
            )

        # 5. Generate LaTeX tables (optional)
        if latex:
            console.print("\n[bold]📝 Generating LaTeX tables...[/bold]")
            latex_str = suite.generate_latex_tables(
                multi_run=multi_run_results,
                scalability=scalability_results,
                cli_comparison=cli_results,
                model_comparison=model_results,
            )
            console.print(f"[green]LaTeX tables saved to {output_dir}/[/green]")

        console.print(f"\n[bold green]✅ Benchmarks complete! Results saved to {output_dir}/[/bold green]")

        if rados_client:
            rados_client.disconnect()

    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    cli(obj={})


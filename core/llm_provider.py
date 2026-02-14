"""
LLM provider abstraction supporting multiple backends.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, model: str, temperature: float = 0.1, max_tokens: int = 2000):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        logger.info(f"Initialized {self.__class__.__name__} with model: {model}")
    
    @abstractmethod
    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate text completion."""
        pass
    
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Generate chat completion with message history."""
        pass
    
    @abstractmethod
    def function_call(self, prompt: str, tools: List[Dict], system: Optional[str] = None) -> Dict[str, Any]:
        """Function calling / tool use."""
        pass


class OllamaProvider(BaseLLMProvider):
    """
    Ollama provider for local LLM inference.
    
    Supports models like: llama3.1, llama3.2, mistral, mixtral, qwen2.5, etc.
    """
    
    def __init__(self, model: str = "llama3.2", host: str = "http://localhost:11434", **kwargs):
        super().__init__(model, **kwargs)
        self.host = host
        
        try:
            import ollama
            self.client = ollama.Client(host=host)
            
            # Verify model is available
            try:
                response = self.client.list()
                # Handle both dict and ListResponse object formats
                if hasattr(response, 'models'):
                    available = [m.model for m in response.models]
                elif isinstance(response, dict):
                    available = [m.get('name', m.get('model', '')) for m in response.get('models', [])]
                else:
                    available = []
                
                model_variants = [model, f"{model}:latest"]
                
                if not any(m in available or any(m in a for a in available) for m in model_variants):
                    logger.warning(f"Model {model} not found. Available: {available}")
                    logger.info(f"Pulling model {model}...")
                    self.client.pull(model)
                    logger.info(f"Model {model} pulled successfully")
                else:
                    logger.info(f"Model {model} verified available")
            except Exception as e:
                logger.warning(f"Could not verify model availability: {e}")
                
        except ImportError:
            logger.error("Ollama package not installed. Run: pip install ollama")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Ollama at {host}: {e}")
            logger.info("Make sure Ollama is running: 'ollama serve'")
            raise
    
    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate text completion."""
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat(
                model=self.model,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens
                }
            )
            
            return response['message']['content']
        
        except Exception as e:
            logger.error(f"Ollama completion failed: {e}")
            raise
    
    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Generate chat completion with message history."""
        try:
            response = self.client.chat(
                model=self.model,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens
                }
            )
            
            return response['message']['content']
        
        except Exception as e:
            logger.error(f"Ollama chat failed: {e}")
            raise
    
    def function_call(self, prompt: str, tools: List[Dict], system: Optional[str] = None) -> Dict[str, Any]:
        """
        Function calling using Ollama with structured output.
        """
        try:
            tools_description = self._format_tools(tools)
            
            function_prompt = f"""You are a function calling assistant. Based on the user's request, determine which function to call and extract the parameters.

Available functions:
{tools_description}

User request: {prompt}

CRITICAL RULES for parameter extraction:
1. Extract EXACT object names from the query. Do not modify, shorten, or infer names.
2. If the query mentions "readme", extract as "readme.md". If it says "README", extract as "README.md".
3. If the query mentions "config.yaml" or "yaml file" with context, extract the exact filename.
4. For context-dependent references like "that file" or "the yaml file", use the EXACT filename if mentioned earlier, otherwise extract the most specific reference.
5. For similarity searches, extract the reference object name exactly as stated.
6. Do NOT add extensions or modify filenames unless explicitly mentioned.
7. For cluster management operations (mark OSD out/in, reweight, create/delete pool, set flags, restart, repair, scrub), use the EXACT management function, NOT diagnose_cluster or cluster_health.
8. For runbook operations (list, execute, suggest), use the specific runbook function.

Examples:
- "show files similar to config.yaml" → {{"function": "find_similar", "parameters": {{"object_name": "config.yaml"}}}}
- "find similar to test.txt" → {{"function": "find_similar", "parameters": {{"object_name": "test.txt"}}}}
- "open the readme" → {{"function": "read_object", "parameters": {{"object_name": "readme.md"}}}}
- "is the cluster healthy?" → {{"function": "cluster_health", "parameters": {{}}}}
- "mark OSD 0 as out" → {{"function": "set_osd_out", "parameters": {{"osd_id": 0}}}}
- "mark OSD 0 back in" → {{"function": "set_osd_in", "parameters": {{"osd_id": 0}}}}
- "reweight OSD 1 to 0.8" → {{"function": "reweight_osd", "parameters": {{"osd_id": 1, "weight": 0.8}}}}
- "create a pool called mypool" → {{"function": "create_pool", "parameters": {{"pool_name": "mypool"}}}}
- "delete pool mypool" → {{"function": "delete_pool", "parameters": {{"pool_name": "mypool"}}}}
- "restart OSD 0" → {{"function": "restart_osd", "parameters": {{"osd_id": 0}}}}
- "repair PG 1.0" → {{"function": "repair_pg", "parameters": {{"pg_id": "1.0"}}}}
- "deep scrub PG 1.1" → {{"function": "deep_scrub_pg", "parameters": {{"pg_id": "1.1"}}}}
- "set noout cluster flag" → {{"function": "set_cluster_flag", "parameters": {{"flag": "noout"}}}}
- "unset noout flag" → {{"function": "unset_cluster_flag", "parameters": {{"flag": "noout"}}}}
- "list available runbooks" → {{"function": "list_runbooks", "parameters": {{}}}}
- "suggest a runbook for degraded PGs" → {{"function": "suggest_runbook", "parameters": {{}}}}
- "execute the OSD recovery runbook" → {{"function": "execute_runbook", "parameters": {{}}}}
- "show me OSD status" → {{"function": "osd_status", "parameters": {{}}}}
- "are there any degraded PGs?" → {{"function": "pg_status", "parameters": {{}}}}
- "show me IOPS and bandwidth" → {{"function": "performance_stats", "parameters": {{}}}}
- "what pools do I have?" → {{"function": "pool_stats", "parameters": {{}}}}
- "show me bytes read and bytes written" → {{"function": "performance_stats", "parameters": {{}}}}

Respond ONLY with a JSON object in this exact format:
{{
    "function": "function_name",
    "parameters": {{
        "param1": "value1",
        "param2": "value2"
    }},
    "reasoning": "brief explanation"
}}"""

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": function_prompt})
            
            response = self.client.chat(
                model=self.model,
                messages=messages,
                format="json",
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens
                }
            )
            
            content = response['message']['content']
            
            # Parse JSON response
            try:
                result = json.loads(content)
                return result
            except json.JSONDecodeError:
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                else:
                    logger.error(f"Could not parse function call response: {content}")
                    raise ValueError(f"Invalid JSON response from LLM")
        
        except Exception as e:
            logger.error(f"Ollama function call failed: {e}")
            raise
    
    def _format_tools(self, tools: List[Dict]) -> str:
        """Format tools for prompt."""
        formatted = []
        for tool in tools:
            name = tool.get('name', 'unknown')
            desc = tool.get('description', '')
            params = tool.get('parameters', {})
            
            param_lines = []
            for pname, pinfo in params.items():
                ptype = pinfo.get('type', 'string')
                required = " (required)" if pinfo.get('required') else " (optional)"
                default = f", default: {pinfo.get('default')}" if 'default' in pinfo else ""
                pdesc = pinfo.get('description', '')
                param_lines.append(f"  - {pname}: {ptype}{required}{default} - {pdesc}")
            
            params_str = "\n".join(param_lines) if param_lines else "  No parameters"
            formatted.append(f"- {name}: {desc}\n{params_str}")
        
        return "\n\n".join(formatted)


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI provider for GPT models with native function calling.
    """
    
    def __init__(self, model: str = "gpt-4-turbo-preview", api_key: Optional[str] = None, **kwargs):
        super().__init__(model, **kwargs)
        
        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key)
        except ImportError:
            logger.error("OpenAI package not installed. Run: pip install openai")
            raise
    
    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate text completion."""
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            return response.choices[0].message.content
        
        except Exception as e:
            logger.error(f"OpenAI completion failed: {e}")
            raise
    
    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Generate chat completion with message history."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            return response.choices[0].message.content
        
        except Exception as e:
            logger.error(f"OpenAI chat failed: {e}")
            raise
    
    def function_call(self, prompt: str, tools: List[Dict], system: Optional[str] = None) -> Dict[str, Any]:
        """
        Function calling using OpenAI's native function calling API.
        """
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            # Convert tools to OpenAI format
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool['name'],
                        "description": tool['description'],
                        "parameters": {
                            "type": "object",
                            "properties": tool['parameters'],
                            "required": [k for k, v in tool['parameters'].items() if v.get('required', False)]
                        }
                    }
                }
                for tool in tools
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            message = response.choices[0].message
            
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                return {
                    "function": tool_call.function.name,
                    "parameters": json.loads(tool_call.function.arguments),
                    "reasoning": message.content or "Function call"
                }
            else:
                # No function call, return text response
                return {
                    "function": "unknown",
                    "parameters": {},
                    "reasoning": message.content
                }
        
        except Exception as e:
            logger.error(f"OpenAI function call failed: {e}")
            raise


def create_llm_provider(config: Dict[str, Any]) -> BaseLLMProvider:
    """
    Factory function to create LLM provider from config.
    
    Args:
        config: Configuration dictionary with 'provider', 'model', etc.
        
    Returns:
        Initialized LLM provider
    """
    provider_type = config.get('provider', 'ollama').lower()
    model = config.get('model', 'llama3.2')
    temperature = config.get('temperature', 0.1)
    max_tokens = config.get('max_tokens', 2000)
    
    if provider_type == 'ollama':
        host = config.get('ollama_host', 'http://localhost:11434')
        return OllamaProvider(
            model=model,
            host=host,
            temperature=temperature,
            max_tokens=max_tokens
        )
    
    elif provider_type == 'openai':
        api_key = config.get('api_key') or config.get('openai_api_key')
        return OpenAIProvider(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens
        )
    
    else:
        raise ValueError(f"Unknown LLM provider: {provider_type}")

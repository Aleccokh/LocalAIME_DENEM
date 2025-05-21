from dataclasses import dataclass
from enum import Enum
import json
import pandas as pd
import argparse
from tqdm import tqdm

from evaluator import ask_llm_aime
from utils.llm import LLM
from utils.logger import Logger

AIME_DATASET = 'resources/aime2024.parquet'
PROMPT = 'Given the problem above, reply with the number inside \\boxed{} to provide the final answer.'
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TIMEOUT_SECS = 10 * 60  # 10 minutes timeout


class ResultType(Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    MISSING = "missing"


@dataclass
class AIMEResult:
    problem_id: int
    problem_text: str
    response_text: str | None
    response_int: int | None
    expected_int: int
    generated_tokens: int | None
    result_type: ResultType
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AIMEResult':
        return cls(
            problem_id=data['problem_id'],
            problem_text=data['problem_text'],
            response_text=data.get('response_text'),
            response_int=data.get('response_int'),
            expected_int=data['expected_int'],
            generated_tokens=data.get('generated_tokens'),
            result_type=ResultType(data['result_type'])
        )
    
    def to_dict(self) -> dict[str, int | str | None]:
        return {
            'problem_id': self.problem_id,
            'problem_text': self.problem_text,
            'response_text': self.response_text,
            'response_int': self.response_int,
            'expected_int': self.expected_int,
            'generated_tokens': self.generated_tokens,
            'result_type': self.result_type.value
        }


def load_aime_dataset() -> list[tuple[int, str, int]]:
    dataset = pd.read_parquet(AIME_DATASET)

    ids = dataset['id'].astype(int).tolist()
    problems = dataset['problem'].tolist()
    answers = dataset['answer'].astype(int).tolist()
    return list(zip(ids, problems, answers))


def calculate_stats(results: list[AIMEResult]) -> dict:
    total = len(results)
    correct = sum(1 for r in results if r.result_type == ResultType.CORRECT)
    wrong = sum(1 for r in results if r.result_type == ResultType.WRONG)
    missing = sum(1 for r in results if r.result_type == ResultType.MISSING)
    
    return {
        'total_problems': total,
        'correct': correct,
        'wrong': wrong,
        'missing': missing,
        'correct_percentage': (correct / total) * 100 if total > 0 else 0,
        'wrong_percentage': (wrong / total) * 100 if total > 0 else 0,
        'missing_percentage': (missing / total) * 100 if total > 0 else 0
    }


def main():
    global AIME_DATASET, PROMPT, DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT_SECS
    
    parser = argparse.ArgumentParser(description='Process AIME dataset with specified model.')
    parser.add_argument('--base-url', type=str, required=True, help='Base URL for the OpenAI-compatible API')
    parser.add_argument('--model', type=str, required=True, help='Name of the model to test')
    parser.add_argument('--api-key', type=str, required=False, default='none', help='API key for the OpenAI-compatible API (optional)')
    parser.add_argument('--max-tokens', type=int, required=False, default=DEFAULT_MAX_TOKENS, help=f'Maximum number of tokens to generate (default: {DEFAULT_MAX_TOKENS})')
    parser.add_argument('--timeout', type=int, required=False, default=DEFAULT_TIMEOUT_SECS, help=f'Timeout in seconds for each request (default: {DEFAULT_TIMEOUT_SECS})')
    parser.add_argument('--disable-qwen3-thinking', action='store_true', help='Disable Qwen3 thinking mode')
    parser.add_argument('-o', '--output', type=str, required=False, default=None, help='Where to write the resulting JSON')
    args = parser.parse_args()

    if not args.output:
        args.output = f'{args.model}.json'
        
    if args.disable_qwen3_thinking and 'qwen3' in args.model.lower():
        PROMPT += '\n\n/no_think'
        Logger.info('main', 'Appending /no_think to prompt for Qwen3')

    aime = load_aime_dataset()
    llm = LLM(args.base_url, args.model, args.api_key)
    results = []

    for id, problem, solution in tqdm(aime, desc='Testing on AIME', ncols=100, unit='problem'):
        llm_solution, llm_response, llm_generated_tokens = ask_llm_aime(
            llm=llm, 
            problem=problem,
            prompt=PROMPT,
            max_tokens=args.max_tokens,
            verbose=True,
            timeout=args.timeout
        )

        if not llm_solution:
            result_type = ResultType.MISSING
            tqdm.write(f'{id}: ❕ Missing')
        elif llm_solution == solution:
            result_type = ResultType.CORRECT
            tqdm.write(f'{id}: ✅ Correct')
        else:
            result_type = ResultType.WRONG
            tqdm.write(f'{id}: ❌ Wrong')
        
        results.append(AIMEResult(
            problem_id=id,
            problem_text=problem,
            response_text=llm_response,
            response_int=llm_solution,
            expected_int=solution,
            generated_tokens=llm_generated_tokens,
            result_type=result_type
        ))

    stats = calculate_stats(results)
    metadata = {
        'model_name': args.model,
        'stats': stats
    }
    output_data = {
        'metadata': metadata,
        'results': [result.to_dict() for result in results]
    }

    Logger.info('main', f'Saving results to {args.output}')
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)


if __name__ == '__main__':
    main()

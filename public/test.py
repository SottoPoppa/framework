'''import framework.core.flow as flow
import framework.core.scheme as scheme


def test(a):
    print("Test function called with argument:", a)
    # Add your test logic here
    return a * 2  # Example operation

@flow.result()
def test2(a):
    print("Test function called with argument:", a)
    # Add your test logic here
    return a * 2  # Example operation

import asyncio

if __name__ == "__main__":
    async def main():
        #a = await flow.pipe(10, test, test2)
        #print("Result from test function:", a)
        print(flow.output(scheme.normalize({"name": "John", "age": 11}, {"name": {"type": "string"}, "age": {"type": "integer"}})))

    asyncio.run(main())'''

'''from framework.core.compile import compile_source
from framework.core.dag.runner import DagRunner
import asyncio

async def main():

    definition = compile_source(
        """
select(
        deps:false,
        default:selected,
        entry:false,
        on_end:"gg"
    ) -> select;
""",
        name="main",
    )

    runner = DagRunner(definition)

    session = await runner.create_session("zio",
        initial_context={
            "selected": "src/infrastructure/presentation/console.py"
        }
    )

    await runner.run(session)

    print(session.results)


if __name__ == "__main__":
    asyncio.run(main())'''


"""
main.py
=======

Pipeline completa:

    DSL
     ↓
    Parser
     ↓
    AST
     ↓
    Compiler
     ↓
    DagDefinition
     ↓
    Dag
     ↓
    DagRunner
     ↓
    Session
     ↓
    Executor

Il linguaggio DSL conosce soltanto il Compiler.

Il runtime DAG non conosce nulla del DSL.
"""

import asyncio
from pprint import pprint

from framework.core.language.parser import Parser
from framework.core.language.compiler import Compiler


# ============================================================================
# DSL
# ============================================================================

SOURCE = r'''
{
    selected: "src/infrastructure/presentation/console.py";
    aaa: "sdsod";
}
'''


# ============================================================================
# MAIN PIPELINE
# ============================================================================

async def main() -> None:

    # ------------------------------------------------------------------------
    # 1. DSL
    # ------------------------------------------------------------------------

    print()
    print("=" * 80)
    print("1. DSL")
    print("=" * 80)

    print(SOURCE)

    # ------------------------------------------------------------------------
    # 2. PARSER
    # ------------------------------------------------------------------------

    print()
    print("=" * 80)
    print("2. PARSER")
    print("=" * 80)

    parser = Parser()

    ast = parser.parse(SOURCE)

    print("✓ DSL parsed",ast)

    # ------------------------------------------------------------------------
    # 3. COMPILER
    # ------------------------------------------------------------------------

    compiler = Compiler()

    dag_definition = compiler.compile(ast, name="main")

    print(dag_definition)

if __name__ == "__main__":
    asyncio.run(main())




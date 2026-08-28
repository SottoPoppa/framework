import framework.service.flow as flow


def test(a):
    print("Test function called with argument:", a)
    # Add your test logic here
    return a * 2  # Example operation

import asyncio

if __name__ == "__main__":
    async def main():
        print("Starting test...")
        a = await flow.pipe(10, test)
        print("Result from test function:", a)

    a = flow.Result(result=flow.Success(value=42),  execution_time_ms=123.45, action="test_action", component="test_component", diagnostics={"info": "test"}, transactions=(flow.Success(value="tx1"), flow.Failure(error="tx2_error")))

    asyncio.run(main())
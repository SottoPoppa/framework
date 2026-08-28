import framework.service.flow as flow


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
        a = await flow.pipe(10, test, test2)
        print("Result from test function:", a)

    asyncio.run(main())
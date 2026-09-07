from .compiler import Compiler
from .parser import Parser
def compile_program(program, *, name='main'): return Compiler().compile(program,name=name)
def compile_source(source, parser=None, *, name='main'):
    return Compiler().compile((parser or Parser()).parse(source),name=name)

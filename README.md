=== Intelligence Graph ===
---
config:
  flowchart:
    curve: linear 
---
graph TD;
        __start__([<p>__start__</p>]):::first
        generate_search_plan(generate_search_plan)
        execute_search(execute_search)
        __end__([<p>__end__</p>]):::last
        __start__ --> generate_search_plan;
        generate_search_plan --> execute_search;
        execute_search --> __end__;
        classDef default fill:#f2f0ff,line-height:1.2
        classDef first fill-opacity:0
        classDef last fill:#bfb6fc


=== Search Subagent Graph ===
---
config:
  flowchart:
    curve: linear
---
graph TD;
        __start__([<p>__start__</p>]):::first
        hybrid_search(hybrid_search)
        rerank(rerank)
        __end__([<p>__end__</p>]):::last
        __start__ --> hybrid_search;
        hybrid_search --> rerank;
        rerank --> __end__;
        classDef default fill:#f2f0ff,line-height:1.2
        classDef first fill-opacity:0
        classDef last fill:#bfb6fc

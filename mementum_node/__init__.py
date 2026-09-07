"""Mementum participant framework.

One framework, several node implementations (proposal §14). Everything in
`mementum_node.core` is the *real* participant core: it knows nothing about
simulation, and the simulator substitutes only the clock, the transport and
the sink (implementation plan §3.2).
"""

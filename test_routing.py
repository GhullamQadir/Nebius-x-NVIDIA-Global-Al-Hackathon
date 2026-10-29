from nexora.backend.app.core.router import ModelRouter, RoutingReason
from nexora.backend.app.models import ModelRegistry
from datetime import datetime

# Create test models
models = [
    ModelRegistry(
        id='1', model_id='model1', display_name='Nano Model', provider='nebius',
        tier='nano', context_capacity=32000, max_output_tokens=2048,
        supports_tools=True, supports_reasoning=False, is_enabled=True,
        created_at=datetime.now(), updated_at=datetime.now()
    ),
    ModelRegistry(
        id='2', model_id='model2', display_name='Super Model', provider='nebius',
        tier='super', context_capacity=64000, max_output_tokens=4096,
        supports_tools=True, supports_reasoning=True, is_enabled=True,
        created_at=datetime.now(), updated_at=datetime.now()
    ),
    ModelRegistry(
        id='3', model_id='model3', display_name='Ultra Model', provider='nebius',
        tier='ultra', context_capacity=128000, max_output_tokens=8192,
        supports_tools=True, supports_reasoning=True, is_enabled=True,
        created_at=datetime.now(), updated_at=datetime.now()
    ),
]

router = ModelRouter(models)

# Test MAX mode
decision = router.route(
    routing_mode='max',
    requested_model_id=None,
    task_text='Create a complex web application with multiple components',
    task_complexity='complex',
    context_size=1000,
    requires_tools=True,
    requires_reasoning=True,
    attempt_number=1,
)
print(f'MAX mode (complex task): {decision.model.model_id} - {decision.reason}')

decision = router.route(
    routing_mode='max',
    requested_model_id=None,
    task_text='Simple hello world',
    task_complexity='simple',
    context_size=50,
    requires_tools=False,
    requires_reasoning=False,
    attempt_number=1,
)
print(f'MAX mode (simple task): {decision.model.model_id} - {decision.reason}')

decision = router.route(
    routing_mode='max',
    requested_model_id=None,
    task_text='Debug this complex issue with reasoning',
    task_complexity='moderate',
    context_size=2000,
    requires_tools=True,
    requires_reasoning=True,
    attempt_number=1,
)
print(f'MAX mode (debug task): {decision.model.model_id} - {decision.reason}')

# Test AUTO mode still works
decision = router.route(
    routing_mode='auto',
    requested_model_id=None,
    task_complexity='simple',
)
print(f'AUTO mode (simple): {decision.model.model_id} - {decision.reason}')

decision = router.route(
    routing_mode='auto',
    requested_model_id=None,
    task_complexity='complex',
)
print(f'AUTO mode (complex): {decision.model.model_id} - {decision.reason}')

# Test FIXED mode
decision = router.route(
    routing_mode='fixed',
    requested_model_id='model2',
)
print(f'FIXED mode: {decision.model.model_id} - {decision.reason}')

print('All routing tests passed!')
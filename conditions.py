import operator
import ast

import gettext
_ = gettext.gettext

class ConditionEvaluator:
    """
    Safe condition evaluator that supports:
    - Basic comparisons (==, !=, <, <=, >, >=)
    - Boolean operations (and, or, not)
    - Math operations (+, -, *, /, //, %, **)
    - Property access (obj.property, obj.nested.property)
    - Parentheses for grouping operations
    - Literals (strings, numbers, booleans, None)
    """
    
    ALLOWED_OPERATORS = {
        # Comparison operators
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        # Boolean operators
        ast.And: operator.and_,
        ast.Or: operator.or_,
        ast.Not: operator.not_,
        # Math operators
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        # Unary operators
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    
    def __init__(self, condition):
        self.condition = condition

        self.error_evaluating = None
    
    def evaluate(self, workflow_elements_all, half_size, half_size_coords):
        if not self.condition:
            return True
        
        condition_to_run = self.condition.get("condition", None)
        
        if condition_to_run is None or condition_to_run.strip() == "":
            return True
        
        # replace && and || and ! with 'and', 'or', 'not'
        condition_to_run = condition_to_run.replace("&&", " and ").replace("||", " or ").replace("!", " not ").replace(" AND ", " and ").replace(" OR ", " or ").replace(" NOT ", " not ").replace("===", "==")
        
        # Build context from workflow elements
        context = {}
        for element in workflow_elements_all:
            context[element.get_id()] = element.get_value(half_size=half_size, half_size_coords=half_size_coords)
        
        try:
            # Parse the condition string into an AST
            tree = ast.parse(condition_to_run, mode='eval')
            result = self._evaluate_node(tree.body, context)
            
            # Ensure result is boolean
            if isinstance(result, bool):
                return result
            else:
                return bool(result)
                
        except (SyntaxError, ValueError) as e:
            self.error_evaluating = f"Error parsing condition '{condition_to_run}': {e}"
            return False
        except Exception as e:
            self.error_evaluating = f"Error evaluating condition '{condition_to_run}': {e}"
            return False
    
    def _evaluate_node(self, node, context):
        """Safely evaluate an AST node"""
        
        if isinstance(node, ast.Compare):
            return self._evaluate_compare(node, context)
        
        elif isinstance(node, ast.BoolOp):
            return self._evaluate_boolop(node, context)
        
        elif isinstance(node, ast.BinOp):
            return self._evaluate_binop(node, context)
        
        elif isinstance(node, ast.UnaryOp):
            return self._evaluate_unaryop(node, context)
        
        elif isinstance(node, ast.Name):
            # Variable lookup
            if node.id in context:
                return context[node.id]
            else:
                raise ValueError(f"Unknown variable: {node.id}")
        
        elif isinstance(node, ast.Attribute):
            # Property access (obj.property)
            return self._evaluate_attribute(node, context)
        
        elif isinstance(node, ast.Constant):
            # Literal values (strings, numbers, booleans, None)
            return node.value
        
        # For Python < 3.8 compatibility
        elif isinstance(node, ast.Str):
            return node.s
        elif isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.NameConstant):
            return node.value
        
        else:
            raise ValueError(f"Unsupported operation: {type(node).__name__}")
    
    def _evaluate_compare(self, node, context):
        """Evaluate comparison operations"""
        left = self._evaluate_node(node.left, context)
        
        result = True
        current_value = left
        
        for op, comparator in zip(node.ops, node.comparators):
            right = self._evaluate_node(comparator, context)
            
            if type(op) not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Unsupported comparison operator: {type(op).__name__}")
            
            op_func = self.ALLOWED_OPERATORS[type(op)]
            comparison_result = op_func(current_value, right)
            
            if not comparison_result:
                result = False
                break
                
            current_value = right
        
        return result
    
    def _evaluate_boolop(self, node, context):
        """Evaluate boolean operations (and, or)"""
        op_type = type(node.op)
        
        if op_type not in self.ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported boolean operator: {op_type.__name__}")
        
        if isinstance(node.op, ast.And):
            # Short-circuit evaluation for 'and'
            for value_node in node.values:
                result = self._evaluate_node(value_node, context)
                if not result:
                    return False
            return True
        
        elif isinstance(node.op, ast.Or):
            # Short-circuit evaluation for 'or'
            for value_node in node.values:
                result = self._evaluate_node(value_node, context)
                if result:
                    return True
            return False
        
        else:
            raise ValueError(f"Unsupported boolean operator: {op_type.__name__}")
    
    def _evaluate_binop(self, node, context):
        """Evaluate binary operations (math operations)"""
        left = self._evaluate_node(node.left, context)
        right = self._evaluate_node(node.right, context)
        
        op_type = type(node.op)
        
        if op_type not in self.ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
        
        op_func = self.ALLOWED_OPERATORS[op_type]
        
        try:
            return op_func(left, right)
        except ZeroDivisionError:
            raise ValueError("Division by zero")
        except Exception as e:
            raise ValueError(f"Error in math operation: {e}")
    
    def _evaluate_unaryop(self, node, context):
        """Evaluate unary operations (not, +, -)"""
        operand = self._evaluate_node(node.operand, context)
        
        op_type = type(node.op)
        
        if op_type not in self.ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        
        op_func = self.ALLOWED_OPERATORS[op_type]
        return op_func(operand)
    
    def _evaluate_attribute(self, node, context):
        """Evaluate attribute access (obj.property)"""
        obj = self._evaluate_node(node.value, context)
        
        if obj is None:
            return None
        
        attr_name = node.attr
        
        # Only allow access to dictionary keys and object attributes
        if hasattr(obj, attr_name):
            return getattr(obj, attr_name)
        elif isinstance(obj, dict) and attr_name in obj:
            return obj[attr_name]
        else:
            raise ValueError(f"Object has no attribute '{attr_name}'")
        
    def get_error_message(self):
        if self.error_evaluating is not None:
            return self.error_evaluating
        return self.condition.get("error", _("Condition {} not met.").format(self.condition.get("condition", "")))
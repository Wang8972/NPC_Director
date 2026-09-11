using System;
using System.Collections;
using System.Collections.Generic;

namespace LastLight
{
    /// <summary>Flattens nested presentation coroutines, so pause, cancellation and errors are never bypassed.</summary>
    public static class PresentationRoutine
    {
        public static IEnumerator Run(IEnumerator routine,Func<bool> cancelled,Action<Exception> failed,Action tick=null)
        {
            if(routine==null)yield break;
            var stack=new Stack<IEnumerator>();stack.Push(routine);
            try
            {
                while(stack.Count>0)
                {
                    if(cancelled())yield break;
                    if(PresentationClock.Paused){yield return null;continue;}
                    tick?.Invoke();
                    var current=stack.Peek();bool moved=false;Exception error=null;
                    try{moved=current.MoveNext();}catch(Exception exception){error=exception;}
                    if(error!=null){failed(error);yield break;}
                    if(!moved){(stack.Pop() as IDisposable)?.Dispose();continue;}
                    if(current.Current is IEnumerator nested){stack.Push(nested);continue;}
                    yield return current.Current;
                }
            }
            finally
            {
                while(stack.Count>0)(stack.Pop() as IDisposable)?.Dispose();
            }
        }
    }
}
